"""
converters.py
===

This file provides translators of repeated checkins.
"""
from discord import (
    VoiceState, 
    CategoryChannel, 
    Member,
)
from checks import (
    get_channel_status,
    is_before_study_session,
    is_after_study_session,
    is_session_cam,
    is_session_ss,
    is_session_activity,
    get_channel_id
)

def get_transition_str(before_status: bool, after_status: bool) -> str:
    """Helper function to convert boolean statuses into transition strings like '10', '01', '11'."""
    return f"{int(before_status)}{int(after_status)}"

def conv_state_to_activity(
    member: Member,
    before: VoiceState, 
    after: VoiceState, 
    session_category: CategoryChannel
) -> dict:
    details = {}
    
    details['beforeChannel'] = get_channel_id(before) or get_channel_id(after)
    
    details["transitions"] = {
        "channel": get_transition_str(get_channel_status(before), get_channel_status(after)),
        "study": get_transition_str(is_before_study_session(before, session_category), is_after_study_session(after, session_category)),
        "cam": get_transition_str(is_session_cam(before), is_session_cam(after)),
        "ss": get_transition_str(is_session_ss(before), is_session_ss(after)),
        "activity": get_transition_str(is_session_activity(before), is_session_activity(after))
    }
    details["user_id"] = member.id
    
    return details