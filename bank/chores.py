"""The bank (Phase 5 part 5b of docs/build-brief-evals.md): chores mined from
real commits of small libraries, one YAML file each under
bank/chores/<library>/<id>.yaml (decision 54). A chore's base is the commit's
parent, its grade is the commit's tests (decision 55) and its reference is
the commit. The split is a hash of the id (decision 34), so it never moves."""

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).parent
CHORES = HERE / "chores"
# The eval's own repo. Its chores never enter the bank (decision 34).
FIXTURE = "thomas-whitley/mercury-fixture"
OWNER = "thomas-whitley"
TRAINING = "training"
VALIDATION = "validation"
# One chore in five is validation (decision 34).
VALIDATION_SHARE = 5
# The worker image's own virtualenv has pytest (decision 57). addopts is
# cleared so a library's pytest config cannot ask for a plugin it lacks.
PYTEST = "python -m pytest -q -p no:cacheprovider -o addopts="


@dataclass(frozen=True)
class Library:
    name: str  # the chore id prefix and folder
    upstream: str  # owner/repo it was forked from
    repo: str  # the fork, thomas-whitley/<repo>
    pythonpath: str = ""  # "src" for a src layout, "" for the repo root

    @property
    def test_command(self) -> str:
        return f"PYTHONPATH={self.pythonpath} {PYTEST}" if self.pythonpath else PYTEST


@dataclass(frozen=True)
class BankChore:
    id: str
    library: str
    repo: str
    instruction: str
    base: str
    reference: str
    grade: tuple[str, ...]  # pytest node ids: fail on the base, pass on the reference
    test_files: tuple[str, ...]  # the commit's test files, copied over a branch to grade it
    split: str


def chore_id(library: str, sha: str) -> str:
    return f"{library}-{sha[:10]}"


def split_of(chore_id: str) -> str:
    digest = int(hashlib.sha256(chore_id.encode()).hexdigest()[:8], 16)
    return VALIDATION if digest % VALIDATION_SHARE == 0 else TRAINING


def load_libraries(path: Path = HERE / "libraries.yaml") -> dict[str, Library]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    libraries = {}
    for entry in data.get("libraries") or []:
        library = Library(**entry)
        if not library.repo.startswith(f"{OWNER}/"):
            raise ValueError(f"{library.name}: the bank runs on forks under {OWNER} only")
        libraries[library.name] = library
    return libraries


def load_bank(directory: Path = CHORES) -> list[BankChore]:
    chores = []
    for path in sorted(directory.glob("*/*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        chore = BankChore(
            **{**data, "grade": tuple(data["grade"]), "test_files": tuple(data["test_files"])}
        )
        if path.stem != chore.id:
            raise ValueError(f"{path.name} holds chore {chore.id}; name the file by its id")
        if chore.repo == FIXTURE:
            raise ValueError(f"{chore.id}: the eval fixture never enters the bank")
        if chore.split != split_of(chore.id):
            raise ValueError(f"{chore.id}: its split is {chore.split}, its hash says otherwise")
        chores.append(chore)
    return chores


def write_chore(chore: BankChore, directory: Path = CHORES) -> Path:
    path = directory / chore.library / f"{chore.id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(chore) | {"grade": list(chore.grade), "test_files": list(chore.test_files)}
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
    return path
