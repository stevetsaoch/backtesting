import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from preset.schemas import PresetOutbound


@dataclass(frozen=True)
class RegisteredPreset:
    name: str
    preset: PresetOutbound
    source_file: Path
    variable_name: str


class PresetRegistry:
    def __init__(self, presets_path: Path):
        self._presets_path = presets_path
        self._by_name: dict[str, RegisteredPreset] = {}

    def load_all(self) -> None:
        self._by_name.clear()

        for py_file in self._iter_preset_files():
            instances = self._extract_instances(py_file)

            if not instances:
                continue

            if len(instances) == 1:
                name = py_file.stem
                self._register(name, instances[0][0], py_file, instances[0][1])
            else:
                for idx, (preset, var_name) in enumerate(instances, start=1):
                    name = f"{py_file.stem}_{idx}"
                    self._register(name, preset, py_file, var_name)

    def _iter_preset_files(self) -> Iterator[Path]:
        for py_file in sorted(self._presets_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            yield py_file

    def _extract_instances(self, py_file: Path) -> list[tuple[PresetOutbound, str]]:
        module = self._import_module(py_file)

        results: list[tuple[PresetOutbound, str]] = []
        for var_name, value in vars(module).items():
            if var_name.startswith("_"):
                continue
            if isinstance(value, PresetOutbound):
                results.append((value, var_name))

        return results

    def _import_module(self, py_file: Path):
        module_name = f"_preset_registry_dynamic.{py_file.stem}"

        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"unable to load preset file: {py_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise ImportError(f"error while load {py_file} : {e}") from e

        return module

    def _register(
        self,
        name: str,
        preset: PresetOutbound,
        source_file: Path,
        variable_name: str,
    ) -> None:
        if name in self._by_name:
            existing = self._by_name[name]
            raise ValueError(
                f"Preset name conflit: '{name}' already been "
                f"{existing.source_file}::{existing.variable_name} registered，"
                f"register denied {source_file}::{variable_name}"
            )

        self._by_name[name] = RegisteredPreset(
            name=name,
            preset=preset,
            source_file=source_file,
            variable_name=variable_name,
        )

    def get(self, name: str) -> PresetOutbound:
        if name not in self._by_name:
            raise KeyError(
                f"unable to file '{name}' 的 preset."
                f"available name: {sorted(self._by_name.keys())}"
            )
        return self._by_name[name].preset

    def all(self) -> dict[str, PresetOutbound]:
        return {name: r.preset for name, r in self._by_name.items()}

    def list_names(self) -> list[str]:
        return sorted(self._by_name.keys())
