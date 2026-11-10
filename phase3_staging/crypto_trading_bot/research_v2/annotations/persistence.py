from __future__ import annotations

import os
import subprocess
from pathlib import Path


DEFAULT_HOST = os.environ.get("TRAIDING_PILOT_S7_SSH_HOST", "wanga@s7")
DEFAULT_KEY = Path(os.environ.get("TRAIDING_PILOT_SSH_KEY", "/home/sergey/.ssh/id_to_nyx"))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("TRAIDING_PILOT_SSH_TIMEOUT", "60"))


def _literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class S7PostgresAnnotationStore:
    """Persist annotations in isolated S7 PostgreSQL through existing SSH access."""

    def __init__(
        self,
        host: str | None = None,
        key: str | Path | None = None,
        database: str = "traiding_pilot",
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.host = host or DEFAULT_HOST
        self.key = Path(key or DEFAULT_KEY)
        self.database = database
        self.timeout_seconds = float(timeout_seconds)

    def save(self, annotation: dict) -> None:
        points=annotation["points"]
        sql=["BEGIN;",f"DELETE FROM research.expert_annotations WHERE annotation_id={_literal(annotation['annotation_id'])};",
             "INSERT INTO research.expert_annotations(annotation_id,symbol,timeframe,start_time,end_time,created_at,expert_source,point_count,notes) VALUES ("+
             ",".join((_literal(annotation["annotation_id"]),_literal(annotation["symbol"]),_literal(annotation["timeframe"]),
                       _literal(annotation["start_time"]),_literal(annotation["end_time"]),_literal(annotation["created_at"]),
                       "'MANUAL'",str(len(points)),_literal(annotation.get("notes",""))))+");"]
        for point in points:
            sql.append("INSERT INTO research.expert_annotation_points(annotation_id,point_index,timestamp,price,snap_source) VALUES ("+
                       ",".join((_literal(annotation["annotation_id"]),str(point["point_index"]),_literal(point["timestamp"]),
                                 str(point["price"]),_literal(point.get("snap_source","NONE"))))+");")
        sql.append("COMMIT;")
        command = [
            "ssh",
            "-i",
            str(self.key),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            self.host,
            "sudo",
            "-n",
            "-u",
            "postgres",
            "psql",
            "-d",
            self.database,
            "-v",
            "ON_ERROR_STOP=1",
        ]
        subprocess.run(
            command,
            input="\n".join(sql),
            text=True,
            check=True,
            capture_output=True,
            timeout=self.timeout_seconds,
        )
