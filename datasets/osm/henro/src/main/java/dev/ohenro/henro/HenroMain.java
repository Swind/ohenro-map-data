package dev.ohenro.henro;

import java.nio.file.Path;

import com.onthegomap.planetiler.Planetiler;
import com.onthegomap.planetiler.config.Arguments;

/**
 * Runs the Henro profile over the Shikoku OSM extract.
 *
 * <p>Override inputs/outputs from the command line:
 * {@code --osm-path=/path/to/shikoku-latest.osm.pbf --output=/path/to/output.pmtiles}
 */
public class HenroMain {

  public static void main(String[] args) {
    var arguments = Arguments.fromArgsOrConfigFile(args);
    Planetiler.create(arguments)
      .setProfile(new HenroProfile())
      .addOsmSource("osm", Path.of("data/sources/shikoku.osm.pbf"), "geofabrik:shikoku")
      .overwriteOutput(Path.of("henro/output/shikoku-henro.pmtiles"))
      .run();
  }
}
