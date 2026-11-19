import threading
import time

from karaoke.jobs import JobQueue
from karaoke.library import Library
from karaoke.models import STAGES, SongMeta
from karaoke.pipeline.runner import Pipeline


def add_song(lib, sid):
    lib.create(SongMeta(id=sid, title=sid, artist="", duration_s=None, source_kind="file",
                        source_ref="f", separator_model="m", pitch_tracker="swiftf0"))


def test_queue_processes_one_at_a_time_in_order(tmp_path):
    lib = Library(tmp_path)
    order = []
    gate = threading.Event()
    for sid in ("a", "b"):
        add_song(lib, sid)

    def slow(l, sid):
        order.append(sid)
        gate.wait(2)
    q = JobQueue(Pipeline(lib, {**{s: (lambda l, sid: None) for s in STAGES}, "acquire": slow}))
    q.start()
    q.enqueue("a")
    q.enqueue("b")
    time.sleep(0.2)
    assert q.position("a") == 0 and q.position("b") == 1 and q.position("zzz") is None
    gate.set()
    q.join()
    q.stop()
    assert order == ["a", "b"] and q.position("a") is None


def test_queue_survives_a_crashing_job(tmp_path):
    lib = Library(tmp_path)
    q = JobQueue(Pipeline(lib, {s: (lambda l, sid: None) for s in STAGES}))
    q.start()
    q.enqueue("non-esiste")
    q.join()
    add_song(lib, "ok")
    q.enqueue("ok")
    q.join()
    q.stop()
    assert lib.get("ok").playable


def test_queue_passes_the_starting_stage(tmp_path):
    lib = Library(tmp_path)
    add_song(lib, "a")
    log = []
    q = JobQueue(Pipeline(lib, {s: (lambda l, sid, s=s: log.append(s)) for s in STAGES}))
    q.start()
    q.enqueue("a")
    q.join()
    log.clear()
    q.enqueue("a", from_stage="notes")
    q.join()
    q.stop()
    assert log == ["notes", "lyrics"]
