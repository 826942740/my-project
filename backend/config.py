"""
config.py — 后端配置管理

负责：
  - 定义项目关键路径（数据库、故事包目录等）
  - 将带连字符的模块目录注册为可导入的 Python 包（module-2-ai → module_2_ai）
  - 配置存档系统的数据库路径

Python 规则：包名不能含 `-`，但目录名含 `-` 是合法的文件系统名称。
解决方案：用 importlib 加载目录，并在 sys.modules 中注册别名。
类比：给快递包裹贴上新标签，让系统能认出它。

所有敏感配置（API Key、endpoint）通过环境变量传入，不写入代码。
"""

import sys
import os
import importlib
import importlib.util
from pathlib import Path

# ── 将项目根目录加入 Python 路径 ──
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

# ── 项目根目录 ──
BASE_DIR = ROOT_DIR

# ── 数据库路径 ──
DB_PATH = BASE_DIR / "saves" / "game.db"

# ── 故事包根目录 ──
STORIES_DIR = BASE_DIR / "module-3-game-rules" / "stories"

# ── 默认故事 ID ──
DEFAULT_STORY_ID = os.getenv("DEFAULT_STORY_ID", "dark_forest")


def _register_module_alias(real_dir_name: str, alias: str,
                            load_order: list = None) -> None:
    """
    将带连字符的目录注册为合法的 Python 包别名。

    原理：
      1. 用 importlib 加载目录作为包（执行 __init__.py）
      2. 将子模块按 load_order 指定的顺序逐个加载（处理内部依赖）
      3. 将所有模块注册到 sys.modules（用下划线别名）

    参数：
      real_dir_name: 实际目录名（含连字符），如 "module-3-game-rules"
      alias:         Python 中使用的别名（下划线），如 "module_3_game_rules"
      load_order:    子模块加载顺序列表（文件名不含 .py），None 则按字母序
    """
    # 如果已经注册过，跳过
    if alias in sys.modules:
        return

    pkg_dir = ROOT_DIR / real_dir_name
    if not pkg_dir.exists():
        raise FileNotFoundError(f"模块目录不存在：{pkg_dir}")

    # ── 第一步：创建并注册包对象 ──
    # 必须先注册包本身，子模块的相对导入才能找到父包
    init_file = pkg_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        alias,
        str(init_file),
        submodule_search_locations=[str(pkg_dir)]
    )
    module = importlib.util.module_from_spec(spec)
    module.__path__ = [str(pkg_dir)]
    module.__package__ = alias
    module.__name__ = alias
    sys.modules[alias] = module    # 先注册，后执行（避免循环依赖）
    spec.loader.exec_module(module)

    # ── 第二步：确定子模块加载顺序 ──
    # 按 load_order 顺序加载，保证依赖关系正确
    if load_order is None:
        # 默认按字母序加载所有 .py 文件（不含 __init__.py）
        load_order = sorted(
            p.stem for p in pkg_dir.glob("*.py")
            if p.name != "__init__.py"
        )

    # ── 第三步：按顺序逐个加载子模块 ──
    for sub_name in load_order:
        py_file = pkg_dir / f"{sub_name}.py"
        if not py_file.exists():
            continue

        full_sub_name = f"{alias}.{sub_name}"

        # 创建子模块规格
        sub_spec = importlib.util.spec_from_file_location(
            full_sub_name,
            str(py_file),
        )
        sub_module = importlib.util.module_from_spec(sub_spec)
        sub_module.__package__ = alias    # 关键：设置父包名，使相对导入能工作
        sub_module.__name__ = full_sub_name
        sys.modules[full_sub_name] = sub_module    # 先注册

        # 执行子模块代码（触发 from .xxx import yyy 等相对导入）
        sub_spec.loader.exec_module(sub_module)

        # 挂载到父包对象上（方便属性访问）
        setattr(module, sub_name, sub_module)


# ── 注册所有带连字符的模块目录 ──
# 注意：需要指定 load_order 确保内部依赖顺序正确

# module-2-ai：client.py 和 prompts.py 互相独立，字母序即可
_register_module_alias(
    "module-2-ai",
    "module_2_ai",
    load_order=["client", "prompts"]
)

# module-3-game-rules：依赖顺序 stats → navigator → card_runner → engine
_register_module_alias(
    "module-3-game-rules",
    "module_3_game_rules",
    load_order=["stats", "navigator", "card_runner", "engine"]
)

# module-4-save-system：models 先于 session 加载
_register_module_alias(
    "module-4-save-system",
    "module_4_save_system",
    load_order=["models", "session"]
)

# ── 配置存档系统使用正确的数据库路径 ──
# 必须在模块注册之后执行
import module_4_save_system.models as db_models
db_models.DB_PATH = DB_PATH
