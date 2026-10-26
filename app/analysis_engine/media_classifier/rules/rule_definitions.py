from .rule import Rule
from .rule_set import RuleSet


RULE_DEFINITIONS: dict[str, RuleSet] = {
    "source": RuleSet([
        Rule("BluRay", "bluray", "BluRay", 100),
        Rule("WEB-DL", "web-dl", "WEB-DL", 90),
        Rule("WEBDL_ALT", "webdl", "WEB-DL", 85),
        Rule("WEBRip", "webrip", "WEBRip", 80),
        Rule("BDRip", "bdrip", "BDRip", 70),
        Rule("DVDRip", "dvdrip", "DVDRip", 60),
        Rule("CAM", "cam", "CAM", 50),
        Rule("TS", "ts", "TS", 40),
    ]),

    "release": RuleSet([
        Rule("REMUX", "remux", "REMUX", 100),
    ]),

    "resolution": RuleSet([
        Rule("2160p", "2160p", "2160p", 100),
        Rule("1080p", "1080p", "1080p", 90),
        Rule("720p", "720p", "720p", 80),
        Rule("480p", "480p", "480p", 70),
    ]),

    "video_codec": RuleSet([
        Rule("HEVC_X265", "x265", "HEVC", 100),
        Rule("HEVC", "hevc", "HEVC", 95),
        Rule("H264_X264", "x264", "H264", 90),
        Rule("H264", "h264", "H264", 85),
        Rule("AV1", "av1", "AV1", 80),
    ]),

    "audio": RuleSet([
        Rule("TRUEHD", "truehd", "TRUEHD", 100),
        Rule("ATMOS", "atmos", "TRUEHD", 95),
        Rule("DTS", "dts", "DTS", 90),
        Rule("EAC3", "eac3", "AC3/EAC3", 85),
        Rule("AC3", "ac3", "AC3/EAC3", 80),
        Rule("AAC", "aac", "AAC", 70),
    ]),

    "hdr": RuleSet([
        Rule("HDR_EXPLICIT", "hdr", "HDR", 100),
        Rule("UHD_BLURAY", "2160p", "HDR", 60),
        Rule("BLURAY_REMUX", "remux", "HDR", 55),
    ]),

    "dolby_vision": RuleSet([
        Rule("DV_FULL", "dolby.vision", "DV", 100),
        Rule("DV_SHORT", "dv", "DV", 90),
    ]),
}