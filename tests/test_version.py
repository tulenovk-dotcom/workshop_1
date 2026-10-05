"""Проверки определения выкаченной версии.

Запуск из корня проекта:

    python3 -m unittest discover tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.version import НЕИЗВЕСТНО, current_commit  # noqa: E402

КОММИТ = "3f0d2ba9c1e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8"


class ОпределениеВерсии(unittest.TestCase):
    def собрать(self, head, ссылки=None, packed=None):
        папка = Path(tempfile.mkdtemp())
        git = папка / ".git"
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "HEAD").write_text(head)
        for имя, значение in (ссылки or {}).items():
            путь = git / имя
            путь.parent.mkdir(parents=True, exist_ok=True)
            путь.write_text(значение)
        if packed:
            (git / "packed-refs").write_text(packed)
        return папка

    def test_обычная_ветка(self):
        папка = self.собрать(
            "ref: refs/heads/main\n", {"refs/heads/main": КОММИТ + "\n"}
        )
        self.assertEqual(current_commit(папка), "3f0d2ba")

    def test_отсоединённая_голова(self):
        """После `git reset --hard` на конкретный коммит бывает и так."""
        папка = self.собрать(КОММИТ + "\n")
        self.assertEqual(current_commit(папка), "3f0d2ba")

    def test_упакованные_ссылки(self):
        """Свежий клон держит ссылки в packed-refs, отдельных файлов нет."""
        папка = self.собрать(
            "ref: refs/heads/main\n",
            packed=f"# pack-refs with: peeled\n{КОММИТ} refs/heads/main\n",
        )
        self.assertEqual(current_commit(папка), "3f0d2ba")

    def test_папки_git_нет(self):
        """Честный ответ лучше выдуманного номера."""
        папка = Path(tempfile.mkdtemp())
        self.assertEqual(current_commit(папка), НЕИЗВЕСТНО)

    def test_мусор_вместо_номера(self):
        папка = self.собрать("ref: refs/heads/main\n", {"refs/heads/main": "абв\n"})
        self.assertEqual(current_commit(папка), НЕИЗВЕСТНО)


if __name__ == "__main__":
    unittest.main()
