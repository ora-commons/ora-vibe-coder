"""Small, user-visible failure types for fixed review execution."""


class OraReviewError(Exception):
    """A technical failure that the review graph must not call PASS or FAIL."""


class MalformedResponse(OraReviewError):
    """A model response is missing a required mechanical wrapper or verdict."""


class CallFailure(OraReviewError):
    """A fresh native or peer call did not return a usable response."""

    def __init__(
        self,
        reason: str,
        next_action: str | None = None,
        *,
        usable_response: str | None = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.next_action = next_action
        self.usable_response = usable_response

    def display(self) -> str:
        if self.next_action:
            return f"{self.reason} Next action: {self.next_action}"
        return self.reason
