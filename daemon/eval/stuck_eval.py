"""Stuck Detection Evaluation — Precision and Recall benchmark.

Self-contained: replays 30 synthetic developer sessions through the real
stuck_detector.update_activity() with mocked timestamps. No daemon, no
Ollama, no external services required.

Usage
-----
    python eval/stuck_eval.py

Output
------
    Prints precision and recall.
    Saves eval/results/stuck_baseline.json.

Session types
-------------
    truly_stuck (15):
        Developer makes an initial meaningful edit, then only tiny edits
        (below the 10-word threshold) for 700-900 s.
        Ground truth: IS stuck. Expected: detector fires (TP).

    reading_code (10):
        Developer makes frequent substantial edits (>10 words each),
        so the timer resets every time. Session lasts 350-550 s.
        Ground truth: NOT stuck. Expected: detector does NOT fire (TN).

    false_alarm (5):
        Developer makes a big initial edit and then stops editing entirely
        for only 450-580 s (below the 600 s threshold).
        Ground truth: NOT stuck. Expected: detector does NOT fire (TN).

Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


_DAEMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DAEMON_DIR))

from contextweave.config import StuckDetectorConfig
from contextweave.db import init_db
from contextweave.stuck_detector import update_activity

_RESULTS_DIR = Path(__file__).parent / "results"





@dataclass
class Event:
    """A file-save event replayed into the stuck detector."""
    time_offset_seconds: float
    content: str
    significant: bool  


@dataclass
class Session:
    session_id: int
    session_type: Literal["truly_stuck", "reading_code", "false_alarm"]
    events: list[Event]
    ground_truth_stuck: bool   
    expected_to_fire: bool     






def _make_sessions() -> list[Session]:
    sessions: list[Session] = []
    sid = 1

    
    
    for i in range(15):
        base_func = f"def authenticate_user_{i}(username, password):\n"
        big_start = base_func + "    # Initial implementation\n    db = get_db()\n    user = db.query(User).filter(User.username == username).first()\n    if not user:\n        return False\n    if not verify_password(password, user.hashed_password):\n        return False\n    return user\n"
        
        end_time = 720 + i * 12
        events = [
            Event(0, big_start, significant=True),
            Event(30, big_start + "    # TODO: add logging\n", significant=False),
            Event(90, big_start + "    # TODO: add logging\n    # check perms\n", significant=False),
        ]
        
        for t in range(150, end_time, 60):
            events.append(Event(t, big_start + f"    # TODO step {t}\n", significant=False))
        events.append(Event(end_time, big_start + "    # still stuck\n", significant=False))
        sessions.append(Session(
            session_id=sid, session_type="truly_stuck", events=events,
            ground_truth_stuck=True, expected_to_fire=True,
        ))
        sid += 1

    
    
    for i in range(10):
        end_time = 380 + i * 18
        events = []
        for t in range(0, end_time, 45):
            block = (
                f"def process_request_{i}_{t}(request, db, user, config, logger):\n"
                f"    # Processing step at offset {t}\n"
                f"    result = db.query(Item).filter(Item.owner_id == user.id).all()\n"
                f"    validated = [schema.ItemOut.model_validate(r) for r in result]\n"
                f"    logger.info('processed request', count=len(validated), user=user.id)\n"
                f"    return validated\n"
            )
            events.append(Event(t, block, significant=True))
        sessions.append(Session(
            session_id=sid, session_type="reading_code", events=events,
            ground_truth_stuck=False, expected_to_fire=False,
        ))
        sid += 1

    
    
    for i in range(5):
        big_edit = (
            f"def create_item_{i}(item_in: ItemCreate, db: Session, current_user: User) -> Item:\n"
            f"    db_item = Item(**item_in.model_dump(), owner_id=current_user.id)\n"
            f"    db.add(db_item)\n"
            f"    db.commit()\n"
            f"    db.refresh(db_item)\n"
            f"    return db_item\n"
        )
        
        end_time = 490 + i * 18
        events = [
            Event(0, big_edit, significant=True),
            Event(60, big_edit, significant=False),    
            Event(end_time, big_edit, significant=False),  
        ]
        sessions.append(Session(
            session_id=sid, session_type="false_alarm", events=events,
            ground_truth_stuck=False, expected_to_fire=False,
        ))
        sid += 1

    return sessions






async def replay_session(
    session: Session,
    db: sqlite3.Connection,
    config: StuckDetectorConfig,
) -> bool:
    """Replay all events and return True if the detector fired at any point.

    Strategy: monkey-patch time.time in the stuck_detector module so all
    calls to time.time() within _update_activity_inner see the simulated
    wall-clock time.  We also pre-seed the chunks table with the initial
    content so _get_last_content() can do a proper word-diff instead of
    treating every hash-change as significant.
    """
    import hashlib
    import contextweave.stuck_detector as _sd

    file_path = f"/workspace/session_{session.session_id}/main.py"
    base_time = time.time() - max(e.time_offset_seconds for e in session.events) - 10

    fired = False
    prev_content: str | None = None

    for idx, event in enumerate(session.events):
        simulated_now = base_time + event.time_offset_seconds

        
        
        if prev_content is not None:
            chunk_id = hashlib.sha256(f"{file_path}:__module__".encode()).hexdigest()[:16]
            try:
                db.execute(
                    "INSERT OR REPLACE INTO chunks "
                    "(id, file_path, chunk_name, chunk_type, content, language, "
                    "start_line, end_line, last_seen, created_at, workspace_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (chunk_id, file_path, "__module__", "module", prev_content,
                     "python", 1, 50, simulated_now - 1, simulated_now - 1, "default"),
                )
                db.commit()
            except Exception:
                pass

        orig_time = _sd.time.time
        _sd.time.time = lambda _t=simulated_now: _t  
        try:
            result = await update_activity(
                file_path=file_path,
                content=event.content,
                db=db,
                config=config,
            )
        finally:
            _sd.time.time = orig_time  

        prev_content = event.content

        if result:
            fired = True
            break  

    return fired







def compute_metrics(results: list[dict]) -> dict:
    tp = sum(1 for r in results if r["fired"] and r["ground_truth_stuck"])
    fp = sum(1 for r in results if r["fired"] and not r["ground_truth_stuck"])
    fn = sum(1 for r in results if not r["fired"] and r["ground_truth_stuck"])
    tn = sum(1 for r in results if not r["fired"] and not r["ground_truth_stuck"])

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }






async def main() -> None:
    config = StuckDetectorConfig(threshold_seconds=600, min_change_tokens=10)
    sessions = _make_sessions()

    print(f"Replaying {len(sessions)} synthetic sessions...")
    print(f"  truly_stuck : {sum(1 for s in sessions if s.session_type == 'truly_stuck')}")
    print(f"  reading_code: {sum(1 for s in sessions if s.session_type == 'reading_code')}")
    print(f"  false_alarm : {sum(1 for s in sessions if s.session_type == 'false_alarm')}")
    print()

    import os
    tmp = tempfile.mktemp(suffix=".db")
    db = init_db(Path(tmp))

    results: list[dict] = []
    try:
        for session in sessions:
            fired = await replay_session(session, db, config)
            correct = fired == session.expected_to_fire
            tag = "TP" if fired and session.ground_truth_stuck else                  "TN" if not fired and not session.ground_truth_stuck else                  "FP" if fired and not session.ground_truth_stuck else "FN"
            results.append({
                "session_id": session.session_id,
                "session_type": session.session_type,
                "ground_truth_stuck": session.ground_truth_stuck,
                "expected_to_fire": session.expected_to_fire,
                "fired": fired,
                "correct": correct,
                "tag": tag,
            })
            print(f"  Session {session.session_id:02d} [{session.session_type:<14}] fired={fired!s:<5}  {tag} {'[OK]' if correct else '[MISS]'}")

    finally:
        db.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass

    metrics = compute_metrics(results)

    print()
    print("=" * 60)
    print(f"  True  Positives (TP): {metrics['true_positives']:>3}  (stuck + detector fired)")
    print(f"  False Positives (FP): {metrics['false_positives']:>3}  (not stuck + fired) — false alarms")
    print(f"  False Negatives (FN): {metrics['false_negatives']:>3}  (stuck + not fired) — missed")
    print(f"  True  Negatives (TN): {metrics['true_negatives']:>3}  (not stuck + not fired)")
    print()
    print(f"  Precision : {metrics['precision'] * 100:.1f}%   (target >= 85%)")
    print(f"  Recall    : {metrics['recall'] * 100:.1f}%   (target >= 70%)")
    print(f"  F1 score  : {metrics['f1'] * 100:.1f}%")
    print("=" * 60)

    _RESULTS_DIR.mkdir(exist_ok=True)
    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_sessions": len(sessions),
        "session_breakdown": {
            "truly_stuck": sum(1 for s in sessions if s.session_type == "truly_stuck"),
            "reading_code": sum(1 for s in sessions if s.session_type == "reading_code"),
            "false_alarm": sum(1 for s in sessions if s.session_type == "false_alarm"),
        },
        "session_results": results,
        "metrics": metrics,
    }
    out_path = _RESULTS_DIR / "stuck_baseline.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
