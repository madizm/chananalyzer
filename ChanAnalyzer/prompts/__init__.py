"""提示词模块"""

from ChanAnalyzer.prompts.analyst import (
    get_analyst_system_prompt,
    get_analyst_user_prompt
)
from ChanAnalyzer.prompts.decision_maker import (
    get_decision_maker_system_prompt,
    get_decision_maker_user_prompt
)

__all__ = [
    "get_analyst_system_prompt",
    "get_analyst_user_prompt",
    "get_decision_maker_system_prompt",
    "get_decision_maker_user_prompt",
]
