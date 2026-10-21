import unittest
from unittest import mock

import src.server as s
from src.utils.readback import reset_verification_stats, verification_stats


class ClipStub:
    def __init__(self, unique_id="clip-1", name="source.mov"):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name

    def GetClipProperty(self, key):
        return "24" if key == "FPS" else None


class FolderStub:
    def __init__(self, clips=None):
        self.clips = clips or []

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return []


class TimelineItemStub:
    def __init__(self, unique_id, name):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.record_start

    def GetEnd(self):
        return self.record_end

    def GetDuration(self):
        return self.record_end - self.record_start

    def GetSourceStartFrame(self):
        return self.source_start

    def GetSourceEndFrame(self):
        return self.source_end

    def GetMediaPoolItem(self):
        return self.clip


class TimelineStub:
    def __init__(self):
        self.items = []

    def GetName(self):
        return "Timeline 1"

    def GetUniqueId(self):
        return "timeline-1"

    def GetSetting(self, key):
        return "24" if key == "timelineFrameRate" else None

    def GetTrackCount(self, track_type):
        return 2 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, track_index):
        if track_type == "video":
            return [i for i in self.items if getattr(i, "track", 1) == track_index]
        return []


class ProjectStub:
    def __init__(self, timeline):
        self.timeline = timeline

    def GetCurrentTimeline(self):
        return self.timeline


class MediaPoolStub:
    def __init__(self, root, timeline):
        self.root = root
        self.timeline = timeline

    def GetRootFolder(self):
        return self.root

    def AppendToTimeline(self, clips):
        appended = []
        for index, row in enumerate(clips, start=1):
            clip = row.get("mediaPoolItem") if isinstance(row, dict) else row
            item = TimelineItemStub(f"timeline-item-{index}", clip.GetName())
            if isinstance(row, dict):
                item.clip = clip
                item.track = row["trackIndex"]
                item.record_start = row["recordFrame"]
                item.source_start = row["startFrame"]
                item.source_end = row["endFrame"]
                item.record_end = item.record_start + row["endFrame"] - row["startFrame"]
            self.timeline.items.append(item)
            appended.append(item)
        return appended


class MediaPoolAppendVerificationTest(unittest.TestCase):
    def test_append_to_timeline_simple_updates_verified_operation_and_stats(self):
        reset_verification_stats()
        clip = ClipStub()
        timeline = TimelineStub()
        project = ProjectStub(timeline)
        media_pool = MediaPoolStub(FolderStub([clip]), timeline)

        with mock.patch.object(s, "_get_mp", return_value=(None, project, media_pool, None)):
            result = s.media_pool("append_to_timeline", {"clip_ids": ["clip-1"]})

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        operation = result["verified_operation"]
        self.assertEqual(operation["name"], "media_pool.append_to_timeline")
        self.assertTrue(operation["verified"])
        self.assertEqual(operation["verification_status"], "readback_verified")
        self.assertEqual(operation["execution"]["success"], True)
        self.assertEqual(operation["readback"]["item_count_delta"], 1)

        stats = verification_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["verified"], 1)
        self.assertEqual(stats["contradicted"], 0)
        self.assertEqual(stats["unverified"], 0)

    def test_append_to_timeline_clip_infos_updates_verified_operation_and_stats(self):
        reset_verification_stats()
        clip = ClipStub()
        timeline = TimelineStub()
        project = ProjectStub(timeline)
        media_pool = MediaPoolStub(FolderStub([clip]), timeline)

        with mock.patch.object(s, "_get_mp", return_value=(None, project, media_pool, None)):
            result = s.media_pool(
                "append_to_timeline",
                {
                    "clip_infos": [
                        {
                            "clip_id": "clip-1",
                            "start_frame": 0,
                            "end_frame": 24,
                            "record_frame": 0,
                            "track_index": 1,
                            "media_type": 1,
                        }
                    ]
                },
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["timeline_item_id"], "timeline-item-1")
        operation = result["verified_operation"]
        self.assertEqual(operation["name"], "media_pool.append_to_timeline")
        self.assertTrue(operation["verified"])
        self.assertEqual(operation["verification_status"], "readback_verified")
        self.assertEqual(operation["readback"]["item_count_delta"], 1)

        stats = verification_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["verified"], 1)


    def _positioned(self, mutate_item=None, mutate_timeline=None, source_start=50, source_end=168):
        clip = ClipStub()
        timeline = TimelineStub()
        project = ProjectStub(timeline)
        pool = MediaPoolStub(FolderStub([clip]), timeline)
        original = pool.AppendToTimeline
        def append(rows):
            items = original(rows)
            if mutate_item:
                mutate_item(items[0])
            if mutate_timeline:
                mutate_timeline(timeline)
            return items
        pool.AppendToTimeline = append
        with mock.patch.object(s, "_get_mp", return_value=(None, project, pool, None)):
            return s.media_pool("append_to_timeline", {"clip_infos": [{
                "clip_id": "clip-1", "start_frame": source_start, "end_frame": source_end,
                "record_frame": 8308, "track_index": 1, "media_type": 1,
            }]})

    def test_positioned_append_does_not_verify_one_frame_short(self):
        result = self._positioned(lambda i: setattr(i, "record_end", i.record_end - 1))
        self.assertTrue(result["success"])
        self.assertFalse(result["verified_operation"]["verified"])
        self.assertEqual(result["verified_operation"]["verification_status"], "api_success_unverified")

    def test_positioned_append_does_not_verify_wrong_source(self):
        result = self._positioned(lambda i: setattr(i, "source_start", i.source_start + 1))
        self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_does_not_verify_wrong_destination(self):
        for attribute, value in [("record_start", 8310), ("track", 2), ("clip", ClipStub("wrong-clip"))]:
            with self.subTest(attribute=attribute):
                result = self._positioned(lambda i: setattr(i, attribute, value))
                self.assertFalse(result["verified_operation"]["verified"])

    def test_append_does_not_verify_changed_timeline_identity(self):
        result = self._positioned(mutate_timeline=lambda t: setattr(t, "GetUniqueId", lambda: "other-timeline"))
        self.assertFalse(result["verified_operation"]["verified"])

    def test_append_does_not_verify_incomplete_track_walk(self):
        def blind_audio(t):
            t.GetTrackCount = lambda typ: 2 if typ == "video" else (_ for _ in ()).throw(RuntimeError("lost bridge"))
        result = self._positioned(mutate_timeline=blind_audio)
        self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_does_not_verify_duplicate_occurrence(self):
        result = self._positioned(mutate_timeline=lambda t: t.items.append(t.items[0]))
        self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_missing_source_rate_is_not_exactly_verified(self):
        def clear_source_rate(item):
            item.clip.GetClipProperty = lambda key: None
        result = self._positioned(clear_source_rate)
        self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_does_not_verify_intermittent_identity(self):
        def unstable_identity(item):
            item.GetUniqueId = mock.Mock(side_effect=[item.unique_id, RuntimeError("lost bridge"), item.unique_id])
        result = self._positioned(unstable_identity)
        self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_does_not_infer_source_end_from_record_duration(self):
        for source_end in (None, 167):
            with self.subTest(source_end=source_end):
                result = self._positioned(lambda i: setattr(i, "source_end", source_end))
                self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_fractional_source_intent_is_not_rounded_to_verified(self):
        result = self._positioned(lambda i: setattr(i, "source_start", 50),
                                  source_start=50.25, source_end=168.25)
        self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_fractional_source_readback_is_not_rounded_to_verified(self):
        for attribute, value in [("source_start", 50.25), ("source_end", 168.25)]:
            with self.subTest(attribute=attribute):
                result = self._positioned(lambda i: setattr(i, attribute, value))
                self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_fractional_record_readback_is_not_rounded_to_verified(self):
        for attribute, value in [("record_start", 8308.25), ("record_end", 8426.25)]:
            with self.subTest(attribute=attribute):
                result = self._positioned(lambda i: setattr(i, attribute, value))
                self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_reports_exact_verification_scope(self):
        result = self._positioned()
        operation = result["verified_operation"]
        self.assertTrue(operation["verified"])
        self.assertEqual(operation["readback"]["verification_scope"], "exact_placement")

    def test_positioned_append_unknown_rate_is_not_exactly_verified(self):
        result = self._positioned(mutate_timeline=lambda t: setattr(t, "GetSetting", lambda key: None))
        self.assertFalse(result["verified_operation"]["verified"])

    def test_positioned_append_mixed_rate_is_not_exactly_verified(self):
        result = self._positioned(mutate_timeline=lambda t: setattr(t, "GetSetting", lambda key: "30"))
        self.assertFalse(result["verified_operation"]["verified"])


if __name__ == "__main__":
    unittest.main()
