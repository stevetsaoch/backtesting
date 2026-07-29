import numpy as np
import datetime
import duckdb
import streamlit as st
import plotly.graph_objects as go

filter_freeze_time = datetime.time(10, 30, 0)


class DayTradeFilterAnalysis:
    def __init__(
        self,
        data_root_dir: str,
        file_name_pattern: str,
        warmup_file_name_pattern: str,
        filter_start_time: datetime.time,
        filter_end_time: datetime.time,
        warmup_data_start_date: datetime.date,
        data_start_date: datetime.date,
        data_end_date: datetime.date,
        symbols: list[str],
        trading_value_lower_limit: list[np.float64],
        amplitude_upper_limit: list[np.float64],
        intraday_absolute_change_upper_limit: list[np.float64],
        gap_upper_limit: list[np.float64],
    ):

        self.symbols = symbols
        self.data_root_dir = data_root_dir
        self.file_name_pattern = file_name_pattern
        self.warmup_file_name_pattern = warmup_file_name_pattern
        self.filter_start_time = filter_start_time
        self.filter_end_time = filter_end_time
        self.warmup_data_start_date = warmup_data_start_date
        self.data_start_date = data_start_date
        self.data_end_date = data_end_date
        self.trading_value_lower_limit = trading_value_lower_limit
        self.amplitude_upper_limit = amplitude_upper_limit
        self.intraday_absolute_change_upper_limit = intraday_absolute_change_upper_limit
        self.gap_upper_limit = gap_upper_limit
        # generated after run
        self.data = {}
        self.warmup_data = {}

    def _load_distinct_data(self):
        for s in self.symbols:
            file_path = f"{self.data_root_dir}{s}/{self.file_name_pattern}"
            raw = duckdb.sql(
                """
                SELECT DISTINCT ON (date) * FROM read_parquet(?) ORDER BY date DESC
                """,
                params=[file_path],
            )
            self.data[s] = raw

    def _load_distinct_warmup_data(self):
        for s in self.symbols:
            file_path = f"{self.data_root_dir}{s}/{self.warmup_file_name_pattern}"
            raw = duckdb.sql(
                """
                SELECT DISTINCT ON (date) * FROM read_parquet(?) ORDER BY date DESC
                """,
                params=[file_path],
            )
            self.warmup_data[s] = raw

    def _trading_value_analysis(self, limits: list[np.float64]):
        result = {
            l: {
                self.data_start_date + datetime.timedelta(days=i): []
                for i in range((self.data_end_date - self.data_start_date).days + 1)
            }
            for l in limits
        }

        for s in self.symbols:
            raw = self.data[s]
            for limit in limits:
                picked_date = duckdb.sql(
                    f"""
                    select date::date as date, sum(volume * average) as indicator from raw
                    where date::time between '{self.filter_start_time}' and '{self.filter_end_time}'
                    and
                    date >= '{self.data_start_date}' and date <= '{self.data_end_date}'
                    group by date::date
                    having  indicator >= {limit}
                    order by date
                    """,
                ).fetchall()
                for k, val in picked_date:
                    result[limit][k].extend([s])
        # fig
        fig = go.Figure()
        for limit, xy in result.items():
            fig.add_trace(
                go.Scatter(
                    x=[k for k in xy.keys()],
                    y=[len(s) for s in xy.values() if len(s) > 0],
                    mode="markers",
                    name=str(limit),
                )
            )
        fig.update_layout(
            title="",
            xaxis_title="Date",
            yaxis_title="Count",
            hovermode="x unified",
            width=1920,
            height=1080,
            xaxis=dict(
                tickmode="linear",
                tickangle=-45,
                tickfont=dict(size=10),
            ),
            yaxis=dict(
                tick0=0,
                dtick=1,
                tickformat="d",
            ),
        )
        return ("Trade Value Analysis", fig)

    def _amplitude_analysis(self, limits: list[np.float64]):
        result = {
            l: {
                self.data_start_date + datetime.timedelta(days=i): []
                for i in range((self.data_end_date - self.data_start_date).days + 1)
            }
            for l in limits
        }

        for s in self.symbols:
            for limit in limits:
                raw = self.data.get(s)
                picked_date = duckdb.sql(
                    f"""

                    SELECT date::DATE as date, (MAX(high) - MIN(low)) / ARG_MIN(open, date) as indicator FROM raw
                    WHERE date::TIME BETWEEN '{self.filter_start_time}' AND '{self.filter_end_time}'
                    AND
                    date >= '{self.data_start_date}' and date <= '{self.data_end_date}'
                    GROUP By date::DATE
                    HAVING  indicator <= {limit}
                    ORDER BY date
                    """,
                ).fetchall()

                for k, val in picked_date:
                    result[limit][k].extend([s])
        # fig
        fig = go.Figure()
        for limit, xy in result.items():
            fig.add_trace(
                go.Scatter(
                    x=[k for k in xy.keys()],
                    y=[len(s) for s in xy.values() if len(s) > 0],
                    mode="markers",
                    name=str(limit),
                )
            )
        fig.update_layout(
            title="Amplitude Analysis",
            xaxis_title="Date",
            yaxis_title="Count",
            hovermode="x unified",
            width=1920,
            height=1080,
            xaxis=dict(
                tickmode="linear",
                tickangle=-45,
                tickfont=dict(size=10),
            ),
            yaxis=dict(
                tick0=0,
                dtick=1,
                tickformat="d",
            ),
        )

        return ("Amplitude Analysis", fig)

    def _absolute_change_analysis(self, limits: list[np.float64]):
        result = {
            l: {
                self.data_start_date + datetime.timedelta(days=i): []
                for i in range((self.data_end_date - self.data_start_date).days + 1)
            }
            for l in limits
        }

        for s in self.symbols:
            for limit in limits:
                raw = self.data.get(s)
                picked_date = duckdb.sql(
                    f"""
                    SELECT date::DATE as date,  ABS(ARG_MAX(close, date) - ARG_MIN(open, date)) / ARG_MIN(open, date) as indicator FROM raw
                    WHERE date::TIME BETWEEN '{self.filter_start_time}' AND '{self.filter_end_time}'
                    AND
                    date >= '{self.data_start_date}' and date <= '{self.data_end_date}'
                    GROUP By date::DATE
                    HAVING  indicator <= {limit}
                    ORDER BY date
                    """,
                ).fetchall()

                for k, val in picked_date:
                    result[limit][k].extend([s])
        # fig
        fig = go.Figure()
        for limit, xy in result.items():
            fig.add_trace(
                go.Scatter(
                    x=[k for k in xy.keys()],
                    y=[len(s) for s in xy.values() if len(s) > 0],
                    mode="markers",
                    name=str(limit),
                )
            )
        fig.update_layout(
            title="Absulate Change Analysis",
            xaxis_title="Date",
            yaxis_title="Count",
            hovermode="x unified",
            width=1920,
            height=1080,
            xaxis=dict(
                tickmode="linear",
                tickangle=-45,
                tickfont=dict(size=10),
            ),
            yaxis=dict(
                tick0=0,
                dtick=1,
                tickformat="d",
            ),
        )

        return ("Amplitude Analysis", fig)

    def _gap_analysis(self, limits: list[np.float64]):
        result = {
            l: {
                self.data_start_date + datetime.timedelta(days=i): []
                for i in range((self.data_end_date - self.data_start_date).days + 1)
            }
            for l in limits
        }

        for s in self.symbols:
            for limit in limits:
                raw = self.warmup_data.get(s)
                picked_date = duckdb.sql(
                    f"""
                    SELECT * FROM (
                    SELECT 
                        date,
                        (open - LAG(close, 1) OVER (ORDER BY date))/ open AS indicator
                    FROM raw
                    WHERE date >= '{self.warmup_data_start_date}' and date <= '{self.data_end_date}'
                    )
                    WHERE indicator <= {limit} 
                    AND 
                    date >= '{self.data_start_date}' and date <= '{self.data_end_date}'
                    ORDER BY date
                    """,
                ).fetchall()

                for k, val in picked_date:
                    result[limit][k].extend([s])
        # fig
        fig = go.Figure()
        for limit, xy in result.items():
            fig.add_trace(
                go.Scatter(
                    x=[k for k in xy.keys()],
                    y=[len(s) for s in xy.values() if len(s) > 0],
                    mode="markers",
                    name=str(limit),
                )
            )
        fig.update_layout(
            title="Gap Analysis",
            xaxis_title="Date",
            yaxis_title="Count",
            hovermode="x unified",
            width=1920,
            height=1080,
            xaxis=dict(
                tickmode="linear",
                tickangle=-45,
                tickfont=dict(size=10),
            ),
            yaxis=dict(
                tick0=0,
                dtick=1,
                tickformat="d",
            ),
        )

        return ("Gap Analysis", fig)

    def report(self):
        self._load_distinct_data()
        self._load_distinct_warmup_data()
        figs = []
        figs.append(self._trading_value_analysis(self.trading_value_lower_limit))
        figs.append(self._amplitude_analysis(self.amplitude_upper_limit))
        figs.append(
            self._absolute_change_analysis(self.intraday_absolute_change_upper_limit)
        )
        figs.append(self._gap_analysis(self.gap_upper_limit))

        for f in figs:
            st.subheader(f[0])
            st.plotly_chart(f[1], width="stretch")


if __name__ == "__main__":
    r = duckdb.sql(
        """
        SELECT DISTINCT(symbol) FROM read_parquet(?);
        """,
        params=[
            "/Volumes/backtesting_main/data/_missions/10_20_1min/2019-12-01 00:00:00|1|minute|23|day.parquet"
        ],
    ).df()

    symbols = r["symbol"].to_list()
    day_trade_filter_analysis = DayTradeFilterAnalysis(
        data_root_dir="/Volumes/backtesting_main/data/",
        file_name_pattern="*23 D|1 min.parquet",
        warmup_file_name_pattern="*20 Y|1 day*.parquet",
        filter_start_time=datetime.time(9, 30, 0),
        filter_end_time=datetime.time(10, 30, 0),
        data_start_date=datetime.date(2020, 1, 1),
        warmup_data_start_date=datetime.date(2019, 12, 20),
        data_end_date=datetime.date(2020, 1, 31),
        symbols=symbols,
        trading_value_lower_limit=[
            v for v in np.arange(20_000_000.0, 120_000_000.0, 10_000_000.0)
        ],
        amplitude_upper_limit=[v for v in np.arange(0.001, 0.012, 0.001)],
        intraday_absolute_change_upper_limit=[
            v for v in np.arange(0.005, 0.025, 0.005)
        ],
        gap_upper_limit=[v for v in np.arange(0.001, 0.022, 0.002)],
    )
    day_trade_filter_analysis.report()
