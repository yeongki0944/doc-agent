"""
Cognito Pre Sign-up Lambda Trigger.
Restricts sign-up to allowed email domains.
"""

ALLOWED_DOMAINS = {"mz.co.kr", "megazone.com"}


def handler(event, context):
    email = event.get("request", {}).get("userAttributes", {}).get("email", "")
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""

    if domain not in ALLOWED_DOMAINS:
        raise Exception(f"이메일 도메인 @{domain}은(는) 허용되지 않습니다. @mz.co.kr 또는 @megazone.com 이메일을 사용해주세요.")

    return event
