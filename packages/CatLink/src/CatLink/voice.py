class VoiceState:
    def __init__(self):
        self.session_id: str | None = None
        self.token: str | None = None
        self.endpoint: str | None = None

    def ready(self) -> bool:
        return all([self.session_id, self.token, self.endpoint])
