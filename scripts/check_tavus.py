"""Check configured Tavus credentials and a Phoenix 4.5 conversation.

Uses Tavus test_mode by default (no rendering or usage charge). --live creates
one short conversation and always ends it; no microphone/camera is accessed.
Run with the backend Python environment from any working directory.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from services.tavus_config import TavusConfig
from services.tavus_service import TavusError


async def check(args: argparse.Namespace) -> int:
    config = TavusConfig()
    config.update_from_headers({})
    service = config.get_service()
    if service is None:
        print("TAVUS_NOT_CONFIGURED: configure the Tavus key in Echo settings.")
        return 1
    pals = await service.list_pals()
    faces = await service.list_faces()
    ready = [face for face in faces if face.get("model_name") == "phoenix-4.5"
             and face.get("status") == "completed"]
    print(json.dumps({"pals": len(pals), "faces": len(faces), "phoenix_4_5_ready": len(ready)}))
    pal_id = args.pal_id or config.pal_id or next(
        (pal["pal_id"] for pal in pals if pal.get("pal_id") and pal.get("default_face_id")), "")
    face = next((face for face in ready if not args.face_id or face.get("face_id") == args.face_id), None)
    if not pal_id or face is None:
        print("No matching PAL or ready Phoenix 4.5 face; choose IDs in PAL Maker.")
        return 1
    print(json.dumps({"pal_id": pal_id, "face_id": face["face_id"], "model": face["model_name"],
                      "test_mode": not args.live}))
    conversation_id = ""
    try:
        result = await service.create_conversation(
            pal_id=pal_id, face_id=face["face_id"],
            conversation_name="Echo Phoenix 4.5 smoke test",
            test_mode=not args.live,
            properties={"max_call_duration": 60, "participant_absent_timeout": 30,
                        "participant_left_timeout": 5},
        )
        conversation_id = result["conversation_id"]
        print(json.dumps({"created": True, "status": result.get("status"),
                          "join_url_present": bool(result.get("conversation_url"))}))
        if args.live:
            await asyncio.sleep(5)
            state = await service._request_json("GET", f"/v2/conversations/{conversation_id}")
            print(json.dumps({"live_status": state.get("status"),
                              "face_id": state.get("face_id", state.get("replica_id"))}))
            if state.get("status") != "active" or state.get("face_id", state.get("replica_id")) != face["face_id"]:
                raise TavusError("TAVUS_SMOKE_FAILED", "The live conversation did not use the selected face.")
    finally:
        if conversation_id and args.live:
            await service.end_conversation(conversation_id)
            state = await service._request_json("GET", f"/v2/conversations/{conversation_id}")
            for _ in range(3):
                if state.get("status") == "ended":
                    break
                await asyncio.sleep(1)
                state = await service._request_json("GET", f"/v2/conversations/{conversation_id}")
            print(json.dumps({"end_requested": True, "status_after_end": state.get("status"),
                              "history_preserved": True}))
            if state.get("status") != "ended":
                raise TavusError("TAVUS_SMOKE_FAILED", "Conversation end was not confirmed.")
    print("PASS: API smoke test. Verify audio/video interactively in Echo's Video PAL page.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pal-id")
    parser.add_argument("--face-id")
    parser.add_argument("--live", action="store_true", help="Run one short billable call, then end it.")
    args = parser.parse_args()
    try:
        return asyncio.run(check(args))
    except TavusError as exc:
        # Never dump provider payloads, credentials, or room tokens.
        print(json.dumps({"error": exc.code, "upstream_status": exc.upstream_status}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
