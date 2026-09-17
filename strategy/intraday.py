import datetime
from strategy.base import BaseCustomStrategyConfig, BaseCustomStrategy
from order.order import OrderState, OrderRole


class ConsolidationAndBreakoutConfig(BaseCustomStrategyConfig, frozen=True):
    pass


class ConsolidationAndBreakout(BaseCustomStrategy):

    def _post_on_bar(self, event):
        # update
        # update signal
        self._signal_manager.update_signals(self._current_session_bars)

        # update mae and mfe
        self._order_ticket_manager.update_mae_mfe(self._current_session_bars)

        # position managing
        if self._position_evaluator.evaluate_forced_close_triggered():
            self.clock.set_time_alert(
                name="forced_close",
                alert_time=self.clock.utc_now().replace(tzinfo=None)
                + datetime.timedelta(seconds=2),
                callback=self._forced_close,
            )
            return
        elif self._position_evaluator.evaluate_exit_signal_triggered():
            self.clock.set_time_alert(
                name="forced_close",
                alert_time=self.clock.utc_now().replace(tzinfo=None)
                + datetime.timedelta(seconds=2),
                callback=self._forced_close,
            )

        # watchlist
        is_watchlist_ready = self._watchlist_manager.is_watchlist_ready
        if not is_watchlist_ready:
            return
        self._signal_manager.register_entry_signal(
            self._watchlist_manager.watchlist,
            established_at=self.clock.utc_now().replace(tzinfo=None),
        )
        # select and ranking candidate
        ranked_candidate = self._candidate_manager.rank_candidate()
        if len(ranked_candidate) == 0:
            self._candidate_manager.reset()
            return

        # pre order validation
        self._order_validator.pre_order_validate(ranked_candidate)
        pre_order_validation_result = self._order_validator.pre_order_validation_result
        final_candidates = []
        for iid, r in pre_order_validation_result.items():
            if all(r.values()):
                final_candidates.append(iid)
        if len(final_candidates) == 0:
            self._order_validator.reset()
            return

        # order compose
        self._order_composer.compose(final_candidates)

        # register
        for otg in self._order_composer.order_ticket_groups:
            self._order_ticket_manager.register_ticket(
                client_order_id=otg.parent.order_client_order_id,
                order_ticket=otg.parent,
            )
            self._order_ticket_manager.register_ticket(
                client_order_id=otg.child.order_client_order_id,
                order_ticket=otg.child,
            )

        # post order validation
        for ot in self._order_ticket_manager.get_tickets_with_specific_state(
            order_state=OrderState.CREATED
        ).values():
            if ot.order_role == OrderRole.PARENT:
                self._order_validator.post_order_validate(ot)

        post_order_validation_result = (
            self._order_validator.post_order_validation_result
        )
        for otci, r in post_order_validation_result.items():
            if all(r.values()):
                self._order_ticket_manager.update_on_post_validation_succeed(
                    otci, self.clock.utc_now().replace(tzinfo=None)
                )
            else:
                self._order_ticket_manager.update_on_post_validation_failed(
                    otci, self.clock.utc_now().replace(tzinfo=None)
                )

        # submit orders
        for ot in self._order_ticket_manager.get_tickets().values():
            if (
                ot.order_state == OrderState.VALIDATION_SUCCESSED
                and ot.order_role == OrderRole.PARENT
            ):
                self.submit_order(ot.order)

        # reset sessionly
        self._candidate_manager.reset()
        self._order_validator.reset()
        self._order_composer.reset()
        self._position_evaluator.reset()
        self._current_session_bars = []

    def _forced_close(self, event):
        if self._position_evaluator.is_forced_close_triggered:
            # order
            ooots = [
                ot
                for ot in self._order_ticket_manager.get_tickets().values()
                if ot.order_state == OrderState.SUBMITTED
                and ot.position_id is None
                and not ot.is_forced_close_order
            ]
            if len(ooots) > 0:
                for ooot in ooots:
                    self.cancel_all_orders(ooot.instrument_id)
            # position
            ots = []
            for id in self._position_evaluator.client_order_ids:
                ots.append(self._order_ticket_manager.get_ticket(id))
            fots = self._order_composer.compose_forced_close_order_ticket(ots)
            for fot in fots:
                self._order_ticket_manager.register_ticket(
                    client_order_id=fot.order_client_order_id, order_ticket=fot
                )
                self.submit_order(fot.order)
        elif self._position_evaluator.is_exit_signal_triggered:
            # close stop lost order
            # position
            cos = []
            ots = []
            for id in self._position_evaluator.client_order_ids:
                pot = self._order_ticket_manager.get_ticket(id)
                co = self._order_ticket_manager.get_ticket(
                    pot.order_child_order_id
                ).order
                cos.append(co)
                ots.append(pot)

            # cancel original stop loss order
            for co in cos:
                self.cancel_order(co)

            # submit force close order
            fots = self._order_composer.compose_forced_close_order_ticket(ots)
            for fot in fots:
                self._order_ticket_manager.register_ticket(
                    client_order_id=fot.order_client_order_id, order_ticket=fot
                )
                self.submit_order(fot.order)

        self._position_evaluator.reset()
