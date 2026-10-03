"""Actionable Live Avatar failures without conflating faces with credentials."""


def format_avatar_error(avatar_name: str, error_text: str) -> str:
    text = error_text.lower()
    if "unsupported avatar name" in text or "unknown avatar" in text:
        return (
            f"Google 不支持分身形象「{avatar_name}」。请使用 Ben，或填写 Google Cloud Studio 中的准确名称。 "
            f'Google does not recognize the avatar "{avatar_name}". Choose Ben or enter the exact name from Google Cloud Studio.'
        )
    if any(term in text for term in ("resource_exhausted", "quota", "429")):
        return (
            "Google 实时分身配额已用尽或请求过于频繁。请稍后重试，或检查 Cloud 项目的配额。 "
            "Google Live Avatar quota or rate limit reached. Retry later or check your Cloud project's quota."
        )
    if any(term in text for term in ("permission_denied", "unauthenticated", "403", "401", "oauth", "permission denied")):
        return (
            "Google 实时分身认证或访问权限不足。请检查 Cloud 凭据、项目和 IAM 模型调用权限。 "
            "Google Live Avatar authentication or access failed. Check Cloud credentials, project and IAM model access."
        )
    return (
        "实时分身会话失败。请重试，并确认 Cloud Studio 中的形象、项目和区域可用。 "
        "Live Avatar session failed. Retry and check that the avatar, project and region work in Cloud Studio. "
        + error_text
    )
