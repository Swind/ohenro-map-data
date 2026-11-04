import unittest

from datasets.arukihenro_routes.classify import classify_point, line_source


class TestClassifyPoint(unittest.TestCase):
    def test_route_endpoint(self):
        self.assertEqual(classify_point("日本, 〒779-0230 徳島県鳴門市大麻町板東 撫養街道"), "route_endpoint")
        self.assertEqual(classify_point("Unnamed Road, 小松町南川 西条市 愛媛県 日本"), "route_endpoint")

    def test_temple_related(self):
        for name in ("極楽寺", "80番札所国分寺", "立江寺奥ノ院", "別格11番生木地蔵", "熊谷寺仁王門", "舎心ケ嶽"):
            self.assertEqual(classify_point(name), "temple_related", name)

    def test_waymarker(self):
        for name in ("真念しるべ石", "江戸期の道しるべ", "土佐街道石碑"):
            self.assertEqual(classify_point(name), "waymarker", name)

    def test_lodging(self):
        for name in ("民宿青空屋", "へんろ宿 越久田屋", "ビジネスホテルMISORA", "大洲しろまちゲストハウス"):
            self.assertEqual(classify_point(name), "lodging", name)

    def test_food_shop(self):
        for name in ("旨いもの（うどん山下）", "三村のパン", "ふくながｃａｆｅ", "酒井軒本舗"):
            self.assertEqual(classify_point(name), "food_shop", name)

    def test_onsen(self):
        self.assertEqual(classify_point("道後温泉"), "onsen")
        self.assertEqual(classify_point("天然温泉きらら"), "onsen")

    def test_hotel_with_onsen_is_lodging(self):
        self.assertEqual(classify_point("神山温泉 ホテル四季の里＆いやしの湯"), "lodging")

    def test_rest_area(self):
        for name in ("道の駅（ひなの里）", "東屋（水井）", "赤野休憩所"):
            self.assertEqual(classify_point(name), "rest_area", name)

    def test_shrine(self):
        for name in ("篠山神社", "月山神社", "多和神社"):
            self.assertEqual(classify_point(name), "shrine", name)

    def test_viewpoint(self):
        for name in ("遠望（薬王寺）", "種間寺遠望", "横峰山を望む"):
            self.assertEqual(classify_point(name), "viewpoint", name)

    def test_route_feature(self):
        for name in ("分岐（右：海岸ルート　左：国道ルート）", "松坂峠", "下川口－三原ル－ト(ル－ト５）"):
            self.assertEqual(classify_point(name), "route_feature", name)

    def test_temple_start_point_stays_temple(self):
        self.assertEqual(classify_point("金泉寺起点"), "temple_related")

    def test_sightseeing(self):
        for name in ("大洲城", "足摺岬灯台", "古い街並み", "夫婦岩", "国宝　十三重石塔", "日本一低い山弁天山（6.1m）"):
            self.assertEqual(classify_point(name), "sightseeing", name)

    def test_elevation_mileage(self):
        for name in ("標高774m", "長戸庵（標高440m）", "十九丁", "国道距離表示（1㎞毎に）"):
            self.assertEqual(classify_point(name), "elevation_mileage", name)

    def test_empty_and_unknown(self):
        self.assertEqual(classify_point(""), "no_name")
        self.assertEqual(classify_point("うまめの木"), "other")

    def test_waymarker_beats_lodging(self):
        self.assertEqual(classify_point("旅人の宿道しるべ"), "waymarker")


class TestLineSource(unittest.TestCase):
    def test_google_directions(self):
        self.assertEqual(
            line_source("日本, 〒779-0230 徳島県鳴門市大麻町板東 撫養街道 から 日本, 〒779-0225 徳島県鳴門市 大麻町桧ダンノ上１２ へのルート"),
            "google_directions",
        )
        self.assertEqual(line_source("Unnamed Road, 三好市 徳島県 日本 から 日本 へのルート"), "google_directions")

    def test_manual(self):
        self.assertEqual(line_source("旧遍路ルート"), "manual")
        self.assertEqual(line_source("香西寺下り"), "manual")


if __name__ == "__main__":
    unittest.main()