import traceback
from PySide6.QtCore import QThread, Signal


class PipelineWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, task_fn):
        super().__init__()
        self.task_fn = task_fn

    def run(self):
        try:
            msg = self.task_fn(self.progress.emit)
            self.finished_ok.emit(str(msg or ""))
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e))
