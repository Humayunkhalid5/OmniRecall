"""Best-effort secret detection: known formats caught, ordinary text kept."""

from __future__ import annotations

import pytest

from omnirecall.capture.sensitive import detect


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow", "private_key"),
        ("-----BEGIN PGP PRIVATE KEY BLOCK-----", "private_key"),
        ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        ("token ghp_" + "a1B2" * 9, "github_token"),
        ("glpat-" + "x" * 20, "gitlab_token"),
        ("xoxb-1234567890-abcdefghij", "slack_token"),
        ("sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc", "stripe_key"),
        ("OPENAI_KEY=sk-proj-" + "A" * 40, "api_key"),
        ("AIza" + "B" * 35, "google_api_key"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N", "jwt"),
        ("password: hunter2abc", "credential_assignment"),
        ("DB_PASSWORD='s3cr3t-value'", "credential_assignment"),
        ("postgres://admin:pa55word@db.internal:5432/app", "connection_string"),
        ("4111-1111-1111-1111", "payment_card"),
        ("5500 0000 0000 0004", "payment_card"),
        ("Xk9#mP2$vL7q", "password_like"),
        ("  correcT-h0rse-battery!  ", "password_like"),
    ],
)
def test_detects_common_secrets(text, kind):
    assert detect(text) == kind


@pytest.mark.parametrize(
    "text",
    [
        "The quarterly review moved to Thursday at 3pm.",
        "error[E0382]: borrow of moved value: `config`",
        "https://example.com/docs/getting-started?lang=en",
        "/home/me/projects/omnirecall/README.md",
        "Order number 1234 5678 9012 3456",  # fails the Luhn check
        "phone +1 (555) 010-2299",
        "2026-10-21T22:14:24.123Z",
        "SELECT * FROM items WHERE status = 'indexed';",
        "password reset instructions are in the wiki",
        "ThisIsJustAWord",
        "v1.2.3-beta",
    ],
)
def test_keeps_ordinary_text(text):
    assert detect(text) is None
