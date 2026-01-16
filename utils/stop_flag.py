class StopFlag:
    """Mutable stop flag for print control threads."""

    def __init__(self):
        self.stop = False
