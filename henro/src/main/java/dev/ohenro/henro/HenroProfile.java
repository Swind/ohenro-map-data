package dev.ohenro.henro;

import java.util.List;

import com.onthegomap.planetiler.FeatureCollector;
import com.onthegomap.planetiler.Profile;
import com.onthegomap.planetiler.reader.SourceFeature;
import com.onthegomap.planetiler.reader.osm.OsmElement;
import com.onthegomap.planetiler.reader.osm.OsmRelationInfo;

/**
 * Extracts OSM hiking route relations into a {@code henro_routes} line layer.
 *
 * <p>This is only the extraction layer: every {@code type=route} +
 * {@code route=hiking} relation is kept as a {@code henro_candidate}. Whether a
 * route is actually part of the Shikoku Henro pilgrimage is a separate
 * classification step (v1.3) that must not be baked into this filter.
 */
public class HenroProfile implements Profile {

  public static final String LAYER_ROUTES = "henro_routes";
  private static final String ROUTE_KIND_CANDIDATE = "henro_candidate";

  @Override
  public List<OsmRelationInfo> preprocessOsmRelation(OsmElement.Relation relation) {
    if (relation.hasTag("type", "route") && relation.hasTag("route", "hiking")) {
      return List.of(new HenroRelationInfo(
        relation.id(),
        stringTag(relation, "name"),
        stringTag(relation, "ref"),
        stringTag(relation, "network"),
        "hiking",
        ROUTE_KIND_CANDIDATE
      ));
    }
    return List.of();
  }

  @Override
  public void processFeature(SourceFeature sourceFeature, FeatureCollector features) {
    if (!sourceFeature.canBeLine()) {
      return;
    }
    // relationInfo() returns the HenroRelationInfo instances that preprocessOsmRelation
    // returned for every relation this way is a member of.
    for (var member : sourceFeature.relationInfo(HenroRelationInfo.class)) {
      HenroRelationInfo info = member.relation();
      FeatureCollector.Feature feature = features.line(LAYER_ROUTES)
        .setAttr("relation_id", info.id())
        .setAttr("route_kind", info.routeKind())
        .setAttr("route", info.route())
        .setZoomRange(0, 14);
      setIfNotNull(feature, "name", info.name());
      setIfNotNull(feature, "ref", info.ref());
      setIfNotNull(feature, "network", info.network());
    }
  }

  private static void setIfNotNull(FeatureCollector.Feature feature, String key, String value) {
    if (value != null) {
      feature.setAttr(key, value);
    }
  }

  private static String stringTag(OsmElement relation, String key) {
    Object value = relation.getTag(key);
    return value == null ? null : value.toString();
  }

  @Override
  public boolean isOverlay() {
    return true;
  }

  @Override
  public String attribution() {
    return OSM_ATTRIBUTION;
  }
}
