"""能力7：长期记忆工具（用户画像读取 + 对话偏好提取）。"""

from langchain.tools import ToolRuntime, tool

from app.memory import extractor
from app.tools.common import to_json


@tool
def get_user_profile(runtime: ToolRuntime) -> str:
    """读取当前用户的偏好画像：偏好类型/演员/导演/地区（来自收藏聚合）、打分习惯
    （来自影评评分）、对话中提取的场景偏好。推荐电影前可以先调用本工具了解用户偏好。"""
    user_id = runtime.context.user_id
    if user_id == 0:
        return "当前是游客，无画像。可基于用户明确说出的偏好推荐"
    profile = extractor.get_or_refresh(user_id)
    return to_json(profile)


@tool
def save_preference(runtime: ToolRuntime, pref_type: str, values: list[str],
                    confidence: str = "high") -> str:
    """把用户在对话中明确表达的偏好存入长期记忆。仅当用户明确说「我喜欢/我讨厌/我一般看」
    等表述时调用；不要从单次观影行为推断偏好。参数：pref_type 为偏好类型，
    可选 scene(观影场景)/watch(年代语言等观影习惯)/genre(类型)/actor(演员)/
    director(导演)/region(地区)；values 为偏好值列表；confidence 为 high 或 medium，
    仅 high 会更新画像（medium 只存档）。"""
    user_id = runtime.context.user_id
    if user_id == 0:
        return "当前是游客，偏好不会被保存。请登录后再使用记忆功能"
    return extractor.record_dialogue_preference(user_id, pref_type, values, confidence)


MEMORY_TOOLS = [get_user_profile, save_preference]
