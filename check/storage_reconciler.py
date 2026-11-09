"""Audit de cohérence entre les segments CutMind en BDD et le stockage physique."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from shared.models.db_models import Segment
from shared.utils.logger import LoggerProtocol, ensure_logger


class StorageState(StrEnum):
    """États possibles lors de la réconciliation stockage / BDD."""

    OK = "ok"
    PATH_MISMATCH = "path_mismatch"
    BDD_MISSING_FILE = "bdd_missing_file"
    DB_FILENAME_MISMATCH = "db_filename_mismatch"
    AMBIGUOUS = "ambiguous"
    UNMATCHED_PHYSICAL = "unmatched_physical"


@dataclass(slots=True, frozen=True)
class ReconcileIssue:
    """Anomalie détectée pendant l'audit."""

    state: StorageState

    segment_id: int | None = None
    uid: str | None = None

    db_path: Path | None = None
    filename_predicted: str | None = None

    physical_paths: tuple[Path, ...] = ()


@dataclass(slots=True)
class ReconcileReport:
    """Résultat complet d'un audit stockage / BDD."""

    db_segments: int = 0
    physical_files: int = 0
    ok: int = 0

    issues: list[ReconcileIssue] = field(default_factory=list)

    def count(self, state: StorageState) -> int:
        """Compte le nombre d'anomalies d'un type donné."""
        return sum(issue.state == state for issue in self.issues)

    @property
    def path_mismatches(self) -> int:
        return self.count(StorageState.PATH_MISMATCH)

    @property
    def missing_files(self) -> int:
        return self.count(StorageState.BDD_MISSING_FILE)

    @property
    def db_filename_mismatches(self) -> int:
        return self.count(StorageState.DB_FILENAME_MISMATCH)

    @property
    def ambiguous(self) -> int:
        return self.count(StorageState.AMBIGUOUS)

    @property
    def unmatched_physical(self) -> int:
        return self.count(StorageState.UNMATCHED_PHYSICAL)


class StorageReconciler:
    """
    Audite la cohérence entre les segments BDD et le stockage physique.

    Cette classe est strictement read-only :
    - aucune modification BDD ;
    - aucun déplacement ;
    - aucune suppression ;
    - aucune modification de pipeline_target.
    """

    def __init__(
        self,
        base_dir: Path,
        logger: LoggerProtocol | None = None,
    ) -> None:
        self.base_dir = base_dir.resolve()
        self.logger = ensure_logger(logger, __name__)

    def audit(
        self,
        segments: list[Segment],
    ) -> ReconcileReport:
        """
        Compare les segments présents en BDD avec les fichiers physiques.

        Ordre de recherche :
        1. correspondance exacte via output_path ;
        2. recherche via filename_predicted ;
        3. détection des correspondances ambiguës ;
        4. détection des fichiers physiques non associés.
        """
        logger = self.logger

        logger.info(
            "🔎 Début audit stockage ↔ BDD : %s",
            self.base_dir,
        )

        physical_paths, physical_by_filename = self._scan_physical_files()

        report = ReconcileReport(
            db_segments=len(segments),
            physical_files=len(physical_paths),
        )

        # Fichiers dont la correspondance avec un segment BDD
        # a été établie avec suffisamment de certitude.
        matched_physical_paths: set[Path] = set()

        # --------------------------------------------------------------
        # Passe 1 : BDD -> filesystem
        # --------------------------------------------------------------
        for segment in segments:
            self._audit_db_segment(
                segment=segment,
                physical_paths=physical_paths,
                physical_by_filename=physical_by_filename,
                matched_physical_paths=matched_physical_paths,
                report=report,
            )

        # --------------------------------------------------------------
        # Passe 2 : filesystem -> BDD
        # --------------------------------------------------------------
        self._find_unmatched_physical_files(
            physical_paths=physical_paths,
            matched_physical_paths=matched_physical_paths,
            report=report,
        )

        self._log_report(report)

        return report

    def _scan_physical_files(
        self,
    ) -> tuple[set[Path], dict[str, list[Path]]]:
        """
        Indexe les fichiers présents sous la racine CutMind.

        Deux index sont construits :
        - ensemble de tous les chemins ;
        - index filename -> liste de chemins.
        """
        physical_paths: set[Path] = set()
        physical_by_filename: dict[str, list[Path]] = {}

        if not self.base_dir.exists():
            self.logger.warning(
                "🚫 Racine de stockage inexistante : %s",
                self.base_dir,
            )
            return physical_paths, physical_by_filename

        if not self.base_dir.is_dir():
            self.logger.warning(
                "🚫 Racine de stockage invalide : %s",
                self.base_dir,
            )
            return physical_paths, physical_by_filename

        self.logger.debug(
            "🔍 Scan physique de %s",
            self.base_dir,
        )

        for path in self.base_dir.rglob("*"):
            if not path.is_file():
                continue

            resolved_path = path.resolve()

            physical_paths.add(resolved_path)

            physical_by_filename.setdefault(
                path.name,
                [],
            ).append(resolved_path)

        self.logger.info(
            "📂 Scan physique terminé : %d fichier(s)",
            len(physical_paths),
        )

        return physical_paths, physical_by_filename

    def _audit_db_segment(
        self,
        segment: Segment,
        physical_paths: set[Path],
        physical_by_filename: dict[str, list[Path]],
        matched_physical_paths: set[Path],
        report: ReconcileReport,
    ) -> None:
        """Contrôle un segment BDD par rapport au stockage physique."""
        db_path = self._get_db_path(segment)

        # --------------------------------------------------------------
        # Contrôle interne BDD :
        #
        # output_path et filename_predicted devraient normalement
        # désigner le même nom de fichier.
        # --------------------------------------------------------------
        if db_path is not None and segment.filename_predicted and db_path.name != Path(segment.filename_predicted).name:
            report.issues.append(
                ReconcileIssue(
                    state=StorageState.DB_FILENAME_MISMATCH,
                    segment_id=segment.id,
                    uid=segment.uid,
                    db_path=db_path,
                    filename_predicted=segment.filename_predicted,
                )
            )

            self.logger.warning(
                "⚠️ Incohérence BDD segment %s : output_path=%s | filename_predicted=%s",
                segment.id,
                db_path,
                segment.filename_predicted,
            )

        # --------------------------------------------------------------
        # Niveau de confiance 1 :
        # output_path existe exactement.
        # --------------------------------------------------------------
        if db_path is not None and db_path in physical_paths:
            matched_physical_paths.add(db_path)
            report.ok += 1
            return

        # --------------------------------------------------------------
        # Niveau de confiance 2 :
        # recherche par filename_predicted.
        # --------------------------------------------------------------
        filename = self._get_expected_filename(segment)

        if filename is None:
            report.issues.append(
                ReconcileIssue(
                    state=StorageState.BDD_MISSING_FILE,
                    segment_id=segment.id,
                    uid=segment.uid,
                    db_path=db_path,
                    filename_predicted=segment.filename_predicted,
                )
            )
            return

        candidates = physical_by_filename.get(
            filename,
            [],
        )

        # Aucun fichier avec ce nom.
        if not candidates:
            report.issues.append(
                ReconcileIssue(
                    state=StorageState.BDD_MISSING_FILE,
                    segment_id=segment.id,
                    uid=segment.uid,
                    db_path=db_path,
                    filename_predicted=segment.filename_predicted,
                )
            )
            return

        # Un seul fichier avec ce nom :
        # forte probabilité que le fichier soit simplement au mauvais endroit.
        if len(candidates) == 1:
            physical_path = candidates[0]

            matched_physical_paths.add(physical_path)

            report.issues.append(
                ReconcileIssue(
                    state=StorageState.PATH_MISMATCH,
                    segment_id=segment.id,
                    uid=segment.uid,
                    db_path=db_path,
                    filename_predicted=segment.filename_predicted,
                    physical_paths=(physical_path,),
                )
            )
            return

        # Plusieurs fichiers portent le même nom.
        #
        # On ne choisit surtout pas arbitrairement.
        report.issues.append(
            ReconcileIssue(
                state=StorageState.AMBIGUOUS,
                segment_id=segment.id,
                uid=segment.uid,
                db_path=db_path,
                filename_predicted=segment.filename_predicted,
                physical_paths=tuple(candidates),
            )
        )

    def _find_unmatched_physical_files(
        self,
        physical_paths: set[Path],
        matched_physical_paths: set[Path],
        report: ReconcileReport,
    ) -> None:
        """
        Identifie les fichiers physiques sans correspondance certaine en BDD.

        Le terme UNMATCHED est volontaire :
        ces fichiers ne doivent pas être considérés comme supprimables.
        """
        unmatched_paths = physical_paths - matched_physical_paths

        for path in sorted(
            unmatched_paths,
            key=str,
        ):
            report.issues.append(
                ReconcileIssue(
                    state=StorageState.UNMATCHED_PHYSICAL,
                    physical_paths=(path,),
                )
            )

    @staticmethod
    def _get_db_path(
        segment: Segment,
    ) -> Path | None:
        """Retourne le chemin BDD normalisé d'un segment."""
        if not segment.output_path:
            return None

        return Path(segment.output_path).resolve()

    @staticmethod
    def _get_expected_filename(
        segment: Segment,
    ) -> str | None:
        """
        Retourne le meilleur nom de fichier connu pour le segment.

        filename_predicted est prioritaire.
        À défaut, le nom contenu dans output_path est utilisé.
        """
        if segment.filename_predicted:
            return Path(segment.filename_predicted).name

        if segment.output_path:
            return Path(segment.output_path).name

        return None

    def _log_report(
        self,
        report: ReconcileReport,
    ) -> None:
        """Affiche le résumé de l'audit."""
        self.logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        self.logger.info("📦 AUDIT STOCKAGE CUTMIND")

        self.logger.info(
            "📌 Segments BDD              : %d",
            report.db_segments,
        )

        self.logger.info(
            "📌 Fichiers physiques         : %d",
            report.physical_files,
        )

        self.logger.info(
            "✅ Correspondances exactes    : %d",
            report.ok,
        )

        self.logger.info(
            "⚠️ Chemins incohérents        : %d",
            report.path_mismatches,
        )

        self.logger.info(
            "❌ Fichiers BDD introuvables  : %d",
            report.missing_files,
        )

        self.logger.info(
            "⚠️ Noms BDD incohérents       : %d",
            report.db_filename_mismatches,
        )

        self.logger.info(
            "⚠️ Correspondances ambiguës   : %d",
            report.ambiguous,
        )

        self.logger.info(
            "❓ Fichiers physiques inconnus : %d",
            report.unmatched_physical,
        )

        self.logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        for issue in report.issues:
            self._log_issue(issue)

    def _log_issue(
        self,
        issue: ReconcileIssue,
    ) -> None:
        """Log le détail d'une anomalie."""
        physical = ", ".join(str(path) for path in issue.physical_paths) if issue.physical_paths else "N/A"

        self.logger.warning(
            "⚠️ AUDIT | %-22s | segment=%s | uid=%s | DB=%s | filename=%s | physique=%s",
            issue.state.value,
            issue.segment_id,
            issue.uid,
            issue.db_path,
            issue.filename_predicted,
            physical,
        )
