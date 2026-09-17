import pandas as pd
from typing import Any
from pathlib import Path
from itertools import product
from pydantic import BaseModel

from preset.schemas import PresetOutbound
from schemas import SweepConfig
from mixin.mixin import FileNameMixin


class PresetRepository(FileNameMixin):
    def __init__(self, root_dir: Path, preset_pairs: dict[str, PresetOutbound]):
        self._preset_pairs: dict[str, PresetOutbound] = preset_pairs
        self._root_dir: Path = root_dir
        self._file_name: str = self.PRESETS_PARQUET

    def save_presets(self):
        """
        save preset from preset_pairs to root_dir / preset_pair.key() / preset.parquet
        """
        self._root_dir.mkdir(parents=True, exist_ok=True)

        for n, preset in self._preset_pairs.items():
            file_dir = self._root_dir / n
            file_dir.mkdir(parents=True, exist_ok=True)
            flat_preset: list[PresetOutbound] = self._flating_preset(preset)
            data = pd.DataFrame([p.model_dump() for p in flat_preset])
            data.to_parquet(
                path=file_dir / self._file_name,
                engine="pyarrow",
                compression="snappy",
                index=False,
            )

    # flat all
    def _flating_preset(self, preset: PresetOutbound):
        flat_presets = []
        flat_presets += self._expand(preset)
        return flat_presets

    # expand preset
    def _find_sweeps(
        self, obj: Any, path: Path | None = None
    ) -> list[tuple[Path, "SweepConfig"]]:
        current_path: Path = () if path is None else path

        found: list[tuple[Path, SweepConfig]] = []

        if isinstance(obj, SweepConfig):
            found.append((current_path, obj))
            return found

        if isinstance(obj, BaseModel):
            for name, value in obj:
                found.extend(self._find_sweeps(value, current_path + (name,)))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                found.extend(self._find_sweeps(item, current_path + (i,)))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                found.extend(self._find_sweeps(v, current_path + (k,)))

        return found

    def _get_at(self, root: Any, path: Path) -> Any:
        obj = root
        for step in path:
            obj = obj[step] if isinstance(step, int) else getattr(obj, step)
        return obj

    def _expand(self, preset: "PresetOutbound") -> list["PresetOutbound"]:
        sweeps = self._find_sweeps(preset)
        if not sweeps:
            return [preset]

        axes = []
        for sweep_path, sweep in sweeps:
            parent_path = sweep_path[:-1]
            sweep_field = sweep_path[-1]
            axes.append(
                [(parent_path, sweep_field, sweep.field_name, v) for v in sweep.values]
            )

        results = []
        for combo in product(*axes):
            new_root = preset.model_copy(deep=True)
            for parent_path, sweep_field, target_field, value in combo:
                parent = self._get_at(new_root, parent_path)
                setattr(parent, target_field, value)
                setattr(parent, sweep_field, None)
            results.append(new_root)

        return results
