from pathlib import Path
from .contracts import PipelineError


def requested(job, parent=None):
    return (Path(job) / 'cancel.request').exists() or bool(parent and Path(parent).exists())


def check(job, parent=None):
    if requested(job, parent):
        raise PipelineError('Задание отменено пользователем', 'CANCELLED')
