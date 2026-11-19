from karaoke.pipeline.progress import ByteProgress, FolderWatcher, reporting_bar


class FakeBar:
    """Il minimo di una barra tqdm: un totale e un contatore."""

    def __init__(self, *args, total=None, **kwargs):
        self.total, self.n, self.closed = total, 0, False

    def update(self, n=1):
        self.n += n

    def close(self):
        self.closed = True


def test_reports_whole_percentages_once_each():
    seen = []
    progress = ByteProgress(seen.append, "Scarico il modello")
    for done in (0, 4, 5, 9, 10, 500, 1000):
        progress.report(done, 1000)
    assert seen == ["Scarico il modello: 0%", "Scarico il modello: 1%", "Scarico il modello: 50%",
                    "Scarico il modello: 100%"]


def test_unknown_total_reports_megabytes():
    seen = []
    progress = ByteProgress(seen.append, "Scarico il modello")
    progress.report(0, 0)
    progress.report(300_000, 0)            # meno di un megabyte: niente di nuovo da dire
    progress.report(52_428_800, 0)
    assert seen == ["Scarico il modello: 0 MB", "Scarico il modello: 50 MB"]


def test_never_goes_over_one_hundred():
    seen = []
    ByteProgress(seen.append, "Scarico").report(1200, 1000)
    assert seen == ["Scarico: 100%"]


def test_reporting_bar_forwards_downloaded_bytes():
    seen = []
    bar_class = reporting_bar(FakeBar, ByteProgress(seen.append, "Scarico il modello"))
    bar = bar_class(total=2000, unit="iB", unit_scale=True)
    bar.update(500)
    bar.update(500)
    bar.close()
    assert seen == ["Scarico il modello: 25%", "Scarico il modello: 50%"] and bar.n == 1000 and bar.closed


def test_folder_watcher_counts_only_what_arrives_after_it_starts(tmp_path):
    (tmp_path / "vecchio.bin").write_bytes(b"x" * 400)
    seen = []
    watcher = FolderWatcher(tmp_path, total=1000, progress=ByteProgress(seen.append, "Scarico"))
    watcher.poll()
    (tmp_path / "blobs").mkdir()
    (tmp_path / "blobs" / "model.incomplete").write_bytes(b"x" * 250)
    watcher.poll()
    (tmp_path / "blobs" / "model.incomplete").write_bytes(b"x" * 1000)
    watcher.poll()
    assert seen == ["Scarico: 0%", "Scarico: 25%", "Scarico: 100%"]


def test_folder_watcher_survives_a_missing_folder(tmp_path):
    seen = []
    FolderWatcher(tmp_path / "non-esiste", total=10, progress=ByteProgress(seen.append, "Scarico")).poll()
    assert seen == ["Scarico: 0%"]
