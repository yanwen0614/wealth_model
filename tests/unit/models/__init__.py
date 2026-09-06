"""让 unittest discover 不遮蔽项目 models 包。"""
from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[3] / "models"))
