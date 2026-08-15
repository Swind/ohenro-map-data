package dev.ohenro.henro;

import com.onthegomap.planetiler.reader.osm.OsmRelationInfo;

/**
 * Metadata about an OSM hiking route relation that is attached to every member
 * way so the way can be re-associated with its relations during processing.
 *
 * <p>Extraction and classification are kept separate: v1 only extracts
 * {@code type=route} + {@code route=hiking} relations and marks them all as
 * {@code henro_candidate}. Real Henro classification happens later.
 */
public record HenroRelationInfo(long id, String name, String ref, String network, String route, String routeKind)
  implements OsmRelationInfo {
}
