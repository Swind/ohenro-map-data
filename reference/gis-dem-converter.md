GSI 四國 DEM 資料轉換與離線 Elevation DB 實作規劃

1. 目標

建立一套可重複執行的離線資料處理工具，將日本國土地理院（GSI）的四國 DEM 資料轉換成適合 Android App 使用的 elevation database。

目前原始資料：

GSI
├── DEM5
│   ├── 5A   (275 個，DEM5A)
│   ├── 5B   (98 個，DEM5B)
│   └── 5C   (44 個，DEM5C)
└── DEM10B   (275 個，原 DEM10)

主要需求：

不使用 DEM1。

DEM5 優先順序為 DEM5A > DEM5B > DEM5C。

DEM10B 作為 DEM5 無資料區域的 fallback。

不要把 ZIP 解壓成大量 XML 檔案到磁碟。

直接從 ZIP 讀取 XML entry，透過 stream / memory buffer 解析。

最終產物提供 Android 端快速執行：

lat/lon -> elevation

route elevation profile

原始 ZIP 保持不變，所有轉換結果均可重新產生。

資料處理流程應能批次執行、驗證、重跑與增量更新。

2. 非目標

第一版不需要：

DEM1。

將 XML/GML 放進 Android App。

GeoJSON elevation points。

將 DEM10B 強行 resample 成假的 5m DEM。

在 Android 端解析 GSI GML。

一開始就做極端壓縮最佳化。

依賴 GSI mesh code 作為 Android runtime API。

GSI mesh code 可以保留於 importer metadata 與 debugging，但不應成為 App 層的主要 abstraction。

3. 整體架構

                   GSI original ZIPs
                          │
             ┌────────────┴────────────┐
             │                         │
           DEM5                      DEM10B
             │                         │
      ┌──────┼──────┐                  │
      │      │      │                  │
    DEM5A  DEM5B  DEM5C                │
      │      │      │                  │
      └──────┬──────┘                  │
             │                         │
       normalized raster        normalized raster
             │                         │
             ▼                         │
     pixel-level priority merge        │
             │                         │
          DEM5 layer                   │
             │                         │
             └──────────┬──────────────┘
                        │
                tiled binary raster
                        │
                compression (zstd)
                        │
                      SQLite
                        │
                    Android
                        │
          elevation(latitude, longitude)

4. 原始資料管理

建議資料目錄：

data/
├── raw/
│   └── gsi/
│       ├── dem5a/
│       │   ├── FG-GML-513462-DEM5A-20251208.zip
│       │   └── ...
│       ├── dem5b/
│       │   └── ...
│       ├── dem5c/
│       │   └── ...
│       └── dem10b/
│           └── ...
│
├── work/
│   ├── index/
│   ├── normalized/
│   └── merged/
│
├── reports/
│
└── output/
    └── shikoku-elevation.sqlite

原則

raw/：

只保存 GSI 原始 ZIP。

不修改。

不將 XML 永久解壓到磁碟。

可以使用 checksum 判斷資料是否更新。

work/：

可刪除。

所有內容都可以由 raw/ 重建。

如果後續發現 intermediate raster 太大，也可以完全不落盤，直接 pipeline 到 tile builder。

output/：

Android 最終使用資料。

5. ZIP 處理方式

5.1 不解壓到檔案系統

禁止採用：

ZIP
 ↓ unzip
數萬個 XML files
 ↓
parser

改成：

ZIP file
   ↓
ZIP reader
   ↓
entry stream
   ↓
XML streaming parser
   ↓
normalized raster

也就是每次只處理一個 ZIP entry。

概念：

open zip

for entry in zip.entries:
    if entry is not *.xml:
        continue

    stream = zip.open(entry)

    raster = parse_gsi_dem_xml(stream)

    process(raster)

    drop raster

XML 不需要產生任何 temporary file。

5.2 記憶體策略

不建議把整個 1.5 GB regional ZIP 一次讀入 RAM。

正確方式是：

disk ZIP
  ↓ seek/read
ZIP entry decompression stream
  ↓
XML streaming parser

亦即：

ZIP archive 保持在磁碟。

一次只 inflate 一個 XML entry。

XML parser 以 streaming/event 模式解析。

不建立完整 DOM。

完成該 raster 後立刻釋放。

如果內層結構是：

regional.zip
  ├── mesh1.zip
  ├── mesh2.zip
  └── ...

則需要支援 nested ZIP。

流程：

regional ZIP
    ↓
inner ZIP entry
    ↓ decompress into memory buffer / temp seekable buffer
    ↓
ZIP reader
    ↓
XML entry stream
    ↓
streaming XML parser

Nested ZIP 的建議

因為 ZIP reader 通常需要 seekable input，內層 ZIP 可以：

小檔案：讀入 Vec<u8> / memory buffer。

若未來遇到非常大的 inner ZIP，再考慮 threshold + temporary file。

目前每個內層 DEM ZIP 大約只有數 MB，直接放記憶體最單純。

因此建議：

outer_zip.open(inner_zip_entry)
    -> read_to Vec<u8>
    -> Cursor<Vec<u8>>
    -> ZipArchive
    -> XML stream

這符合「不留下大量 XML」的需求。

6. XML / GML Parser

目前範例：

<DEM gml:id="DEM001">

 <fid>fgoid:10-00100-25-60101-51346278</fid>

 <type>5mメッシュ（標高）</type>

 <mesh>51346278</mesh>

 <gml:Envelope srsName="fguuid:jgd2024.bl">
   <gml:lowerCorner>34.558333333 134.35</gml:lowerCorner>
   <gml:upperCorner>34.566666667 134.3625</gml:upperCorner>
 </gml:Envelope>

 <gml:Grid dimension="2">
   <gml:limits>
     <gml:GridEnvelope>
       <gml:low>0 0</gml:low>
       <gml:high>224 149</gml:high>
     </gml:GridEnvelope>
   </gml:limits>
 </gml:Grid>

 <gml:tupleList>
 ...
 </gml:tupleList>

這代表：

width  = 224 - 0 + 1 = 225
height = 149 - 0 + 1 = 150

sample count = 33,750

7. Parser 必須擷取的 metadata

建議資料結構：

GsiDemRaster {
    mesh_code
    source
    survey_date

    crs

    lower_lat
    lower_lon
    upper_lat
    upper_lon

    grid_low_x
    grid_low_y
    grid_high_x
    grid_high_y

    width
    height

    sequence_rule
    start_point

    samples[]
}

source：

DEM5A
DEM5B
DEM5C
DEM10B

8. XML 必須使用 streaming parser

不要使用 DOM parser。

錯誤：

read XML entirely
 ↓
parse DOM tree
 ↓
read tupleList

大型批次資料會增加：

RAM 使用量

allocation

GC / allocator pressure

processing time

應採 SAX / pull / event parser：

StartElement
Text
EndElement

只保留目前需要的欄位。

如果使用 Rust，優先考慮：

quick-xml

並直接接收：

impl BufRead

或等價 streaming interface。

9. tupleList Parsing

範例：

海水面,-9999.
データなし,-9999.
データなし,-9999.
地表面,123.45

不能只解析第二欄。

必須保留第一欄語義。

建議 normalized sample：

enum SampleKind {
    Terrain,
    Sea,
    NoData,
}

以及：

struct ElevationSample {
    kind: SampleKind,
    elevation: Option<f32>,
}

實際大量資料處理時不一定真的為每個 sample 建 struct，避免記憶體 overhead。

推薦 SoA 或 compact representation：

elevation: Vec<f32>
mask:      Vec<u8>

mask：

0 = NODATA
1 = TERRAIN
2 = SEA

10. 海水面與 NoData 必須分開

例如：

海水面,-9999

與：

データなし,-9999

雖然數字相同，但語義不同。

推薦 normalization：

SEA:
    elevation = 0.0
    mask = SEA

NODATA:
    elevation = NaN / undefined
    mask = NODATA

Terrain:
    elevation = parsed value
    mask = TERRAIN

不要把 -9999 當真實 elevation。

11. Grid traversal 必須由 XML 決定

Importer 不可以硬寫：

tupleList[0] = south-west pixel

或：

tupleList[0] = north-west pixel

必須解析 GML 中：

sequenceRule
startPoint
GridFunction

等資訊。

第一階段先建立 parser inspection command：

gsi-dem inspect FG-GML-513462-DEM5A-20251208.zip

輸出：

mesh:          51346278
source:        DEM5A
size:          225 x 150
lower corner:  ...
upper corner:  ...
sequence rule: ...
start point:   ...
samples:       33750
valid:         ...
sea:           ...
nodata:        ...

在確認 traversal 規則之前，不要實作正式 pixel -> coordinate mapping。

12. Coordinate Model

內部 normalized raster 應保留 geographic coordinate。

不要在 importer 階段轉 Web Mercator。

建議：

RasterGrid {
    min_lat
    min_lon

    max_lat
    max_lon

    width
    height
}

並從 XML grid/traversal 定義推導：

row,column <-> latitude,longitude

Android runtime 最終 API：

elevation(lat, lon)

而不是：

elevation(gsi_mesh_code, x, y)

13. Normalized Raster

Importer 的 canonical representation：

NormalizedRaster {
    source
    mesh_code

    width
    height

    bounds

    elevation: float32[]
    validity: uint8[]
}

DEM5 範例：

225 × 150
= 33,750 samples

不要使用 JSON 保存 raster values。

14. 是否需要 intermediate file

支援兩種 mode。

Development / debug mode

ZIP
 ↓
NormalizedRaster
 ↓
normalized intermediate

方便：

inspect

visualize

verify parser

重複測試 merge

Production build mode

ZIP
 ↓
NormalizedRaster
 ↓
merge
 ↓
tile builder
 ↓
SQLite

全程 streaming，不落 XML，也可以不落 normalized raster。

CLI 可以提供：

gsi-dem build --keep-intermediate

與：

gsi-dem build

15. DEM5 Merge 規則

來源優先序：

DEM5A > DEM5B > DEM5C

重要：

priority 是 per-pixel，不是 per-file。

例如：

DEM5A

A A A A
A A N N
A N N N

DEM5B：

B B B B
B B B B
B B B B

結果：

A A A A
A A B B
A B B B

Pseudo code：

for sample:

    if DEM5A valid:
        result = DEM5A

    else if DEM5B valid:
        result = DEM5B

    else if DEM5C valid:
        result = DEM5C

    else:
        result = NODATA

16. Source metadata

建議最終保留來源資訊。

0 = NODATA
1 = DEM10B
2 = DEM5C
3 = DEM5B
4 = DEM5A

這可以用於：

debugging

quality inspection

未來 UI 顯示資料品質

驗證 fallback 是否異常

檢查 DEM5 coverage

第一版可以直接一個 u8/sample。

之後若容量有必要再做 bit packing。

17. DEM10B

DEM10B 不應預先強制轉成 DEM5。

保留獨立 layer：

DEM5
DEM10

runtime query：

result = dem5.query(lat, lon)

if result is valid:
    return result

return dem10.query(lat, lon)

如此不會讓 10m 資料看起來像真正的 5m resolution。

18. Final Tile Model

GSI 原始 raster 為：

225 × 150

但 final App tile 不必沿用 GSI mesh 邊界。

建議重新切：

256 × 256 samples

優點：

cache 友善

indexing 單純

compression 單純

不綁定 GSI distribution format

未來可加入其他 DEM source

19. Tile Coordinate System

第一版建議使用 geographic fixed grid，而不是 Web Mercator。

也就是定義整個 elevation dataset 的 origin 與 resolution：

dataset_origin_lat
dataset_origin_lon

resolution_lat
resolution_lon

tile：

tile_size = 256

查詢：

global_x = longitude_to_grid_x(lon)
global_y = latitude_to_grid_y(lat)

tile_x = global_x / 256
tile_y = global_y / 256

pixel_x = global_x % 256
pixel_y = global_y % 256

這樣 Android 不需要 Web Mercator projection。

20. Elevation Encoding

Normalized 階段：

float32

Final database 建議：

int16

以 1 meter 為單位：

elevation = round(meters)

特殊值：

-32768 = NODATA

SEA 可直接：

0m + source/mask = SEA

或保留另一個特殊值。

對 hiking elevation profile，1m vertical resolution 足夠，而且可大幅降低資料量。

如果未來明確需要 sub-meter elevation，再重新評估 encoding。

21. Tile Binary Format

第一版保持簡單。

Elevation tile：

int16[256 * 256]

little-endian：

131072 bytes raw

Source tile：

uint8[256 * 256]

若需要。

不要第一版就自行發明複雜 delta codec。

22. Compression

推薦：

Zstandard (zstd)

pipeline：

int16 raster
    ↓
zstd
    ↓
SQLite BLOB

理由：

elevation raster spatial correlation 高

解壓速度快

Android / Rust 都容易取得實作

random tile read 方便

不需要一次解壓整個四國

23. SQLite Schema

建議 metadata：

CREATE TABLE metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

例如：

format_version
created_at
dataset
horizontal_datum
tile_size
dem5_resolution
dem10_resolution
compression
encoding

Elevation tiles

CREATE TABLE elevation_tiles (
    layer       INTEGER NOT NULL,
    tile_x      INTEGER NOT NULL,
    tile_y      INTEGER NOT NULL,

    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,

    data        BLOB NOT NULL,

    PRIMARY KEY (layer, tile_x, tile_y)
);

Layer：

5  = DEM5
10 = DEM10

Optional source tiles

CREATE TABLE source_tiles (
    layer       INTEGER NOT NULL,
    tile_x      INTEGER NOT NULL,
    tile_y      INTEGER NOT NULL,

    data        BLOB NOT NULL,

    PRIMARY KEY (layer, tile_x, tile_y)
);

24. Dataset Geometry Metadata

不要在每一 tile 重複保存：

origin
resolution

如果整個 layer 是固定 grid，可以放 metadata：

dem5.origin_lat
dem5.origin_lon
dem5.step_lat
dem5.step_lon
dem5.tile_size

dem10.origin_lat
dem10.origin_lon
dem10.step_lat
dem10.step_lon
dem10.tile_size

可明顯減少 metadata 重複。

25. Runtime Query

Android API：

interface ElevationRepository {
    suspend fun elevation(
        latitude: Double,
        longitude: Double
    ): ElevationResult?
}

Result：

data class ElevationResult(
    val meters: Float,
    val source: ElevationSource
)

內部：

lat/lon
  ↓
DEM5 tile coordinate
  ↓
read SQLite blob
  ↓
zstd decompress
  ↓
sample/interpolate
  ↓
valid?
   ├── yes → return
   └── no
          ↓
        DEM10

26. Interpolation

第一版推薦支援：

nearest neighbor
bilinear

route elevation profile 建議用 bilinear。

但是：

若 interpolation 需要的四個 sample 中包含 NODATA，不要直接將 NODATA 當數值。

策略可以是：

有足夠 valid neighbors → interpolation。

否則 nearest valid。

DEM5 無有效值 → fallback DEM10B。

27. Route Elevation Profile

不要每一個 route vertex 都直接當最終 profile sample。

流程：

GeoJSON / GPX route
      ↓
distance-based resampling
      ↓
例如每 10~20m
      ↓
elevation query
      ↓
smoothing
      ↓
profile

Elevation profile：

distance
elevation
cumulative_ascent
cumulative_descent

累積爬升不能直接把所有 microscopic difference 相加，否則 DEM noise 會讓 ascent 被高估。

後續另行設計：

smoothing

noise threshold

minimum ascent segment

28. CLI 工具

建議建立單一 CLI：

gsi-dem

commands：

gsi-dem inspect
gsi-dem index
gsi-dem validate
gsi-dem build
gsi-dem query
gsi-dem profile

inspect

gsi-dem inspect \
  data/raw/gsi/dem5a/FG-GML-513462-DEM5A-20251208.zip

輸出：

Archive: ...
Source: DEM5A

Meshes:
  51346200
  51346201
  ...

Raster:
  size
  bounds
  sequence
  valid count
  sea count
  nodata count

index

掃描所有 ZIP，但不轉換：

gsi-dem index data/raw/gsi/

輸出：

reports/gsi-index.json

內容：

{
  "files": [],
  "mesh_count": {},
  "source_count": {},
  "date_range": {},
  "warnings": []
}

用來確認：

DEM5A = 275 archives
DEM5B = 98 archives
DEM5C = 44 archives
DEM10B = 275 archives

以及實際 XML mesh coverage。

validate

驗證：

XML 是否能解析。

mesh code 是否一致。

sample count 是否等於 width × height。

bounds 是否合理。

source 是否符合資料夾。

tuple type 是否為已知值。

sequenceRule 是否支援。

是否存在 overlapping raster。

是否存在 conflicting metadata。

build

gsi-dem build \
  --input data/raw/gsi \
  --output output/shikoku-elevation.sqlite

可選：

--threads N
--keep-intermediate
--report reports/build.json

query

gsi-dem query \
  output/shikoku-elevation.sqlite \
  --lat 34.123 \
  --lon 134.456

輸出：

Elevation: 432 m
Source: DEM5A

方便與 GSI 地圖人工驗證。

29. Parallel Processing

ZIP/XML parsing 可以 parallelize，但不要無限制開 thread。

推薦：

producer:
    archive paths

workers:
    unzip entry
    parse XML
    generate raster

consumer:
    merge / tile writer

若 SQLite writer 為單一 writer：

workers
   ↓
bounded channel
   ↓
DB writer

這樣避免：

同時大量 allocation

RAM 暴增

SQLite write contention

30. Backpressure

必須使用 bounded queue。

錯誤：

275 ZIP
 ↓
全部 parse
 ↓
大量 raster 留在 RAM

正確：

parser workers
    ↓
bounded channel (例如 8~32 raster)
    ↓
merge / tile builder

producer 太快時自然等待。

31. Incremental Build

每個 source archive 記錄：

path
size
mtime
sha256
source
date

保存 build manifest：

reports/build-manifest.json

下一次 GSI 更新時，可以知道哪些 ZIP 改變。

第一版可以先 full rebuild；schema 與 pipeline 仍應避免阻礙未來 incremental build。

32. Error Handling

遇到單一 XML 錯誤時：

預設 build fail。

不要 silent skip。

Error 至少包含：

outer ZIP
inner ZIP
XML entry
mesh code
source
parser stage

例如：

failed parsing DEM tupleList

outer:
  FG-GML-shikoku-DEM5-20260522-Z001.zip

inner:
  FG-GML-513462-DEM5A-20251208.zip

entry:
  FG-GML-5134-62-78-DEM5A-20251208.xml

mesh:
  51346278

33. Logging

支援：

INFO
DEBUG
WARN
ERROR

INFO 不應逐 sample 輸出。

推薦：

INFO archive started
INFO archive completed
INFO build progress
WARN unsupported/strange metadata
ERROR parse failure

34. Validation / Testing

Unit Tests

至少包含：

XML metadata

bounds

mesh

date

source

grid size

tupleList

terrain

sea

nodata

negative elevation

decimal elevation

Grid traversal

建立小型 synthetic 2×2 或 3×2 GML fixture，驗證：

tuple index ↔ row/column ↔ coordinate

Merge

驗證：

DEM5A > DEM5B > DEM5C

是 pixel-level。

DEM10 fallback

DEM5 NODATA 才能使用 DEM10。

35. Integration Tests

拿真實：

FG-GML-513462-DEM5A-20251208.zip

至少驗證：

可直接從 ZIP parse。

不會產生 XML file。

所有 XML entries 可讀。

每個 raster sample count 正確。

bounds 正確。

可以寫入 SQLite。

query 後可以讀回 elevation。

36. Golden Data

選擇約 20~50 個已知座標：

coast
city
mountain
temple area
DEM5A/5B boundary
DEM5/DEM10 fallback area

保存：

tests/golden/elevation.json

每次 build 跑 regression。

不要要求與 GSI UI 完全 bit-identical；需定義合理 tolerance。

37. Visual Verification

建議 debug command：

gsi-dem render-mesh \
  --mesh 51346278 \
  --output reports/51346278.png

顯示 grayscale / terrain raster。

用途：

快速發現：

north/south flipped

east/west flipped

row stride 錯

sequence rule 錯

NoData 錯

這一步對 DEM parser 非常重要。

38. Rust 專案建議結構

若使用 Rust：

gsi-dem/
├── Cargo.toml
├── src/
│   ├── main.rs
│   │
│   ├── cli/
│   │   ├── inspect.rs
│   │   ├── index.rs
│   │   ├── validate.rs
│   │   ├── build.rs
│   │   └── query.rs
│   │
│   ├── gsi/
│   │   ├── archive.rs
│   │   ├── xml.rs
│   │   ├── mesh.rs
│   │   ├── model.rs
│   │   └── error.rs
│   │
│   ├── raster/
│   │   ├── grid.rs
│   │   ├── merge.rs
│   │   ├── sample.rs
│   │   └── interpolation.rs
│   │
│   ├── tile/
│   │   ├── index.rs
│   │   ├── encoder.rs
│   │   └── compression.rs
│   │
│   └── db/
│       ├── schema.rs
│       ├── writer.rs
│       └── reader.rs
│
└── tests/
    ├── fixtures/
    └── golden/

39. Rust Library 建議

可考慮：

zip
quick-xml
rusqlite
zstd
clap
serde
serde_json
thiserror
tracing
rayon / tokio

注意：

這個工作大部分是：

filesystem I/O

ZIP decompression

XML parsing

CPU processing

不是 network async workload。

因此不必為了使用 Tokio 而把整條 pipeline async 化。

rayon + bounded channel + single DB writer 可能更單純。

如果專案已有 Tokio，再以 spawn_blocking 管理 blocking pipeline 也可以。

40. Archive Abstraction

建議把 ZIP 存取封裝，不讓 XML parser 知道檔案是否來自：

filesystem

outer ZIP

nested ZIP

memory

例如：

trait DemSource {
    fn entries(&mut self) -> ...;
}

XML parser 最終只接受：

fn parse_dem<R: BufRead>(reader: R) -> Result<NormalizedRaster>

如此即可做到：

ZIP entry stream
      ↓
BufReader
      ↓
parse_dem()

完全不需要 XML temporary file。

41. Nested ZIP Memory Guard

雖然目前 inner ZIP 只有數 MB，仍建議加入限制。

例如：

max_inner_zip_size = 64 MiB

超過：

error

或切換 temporary seekable file。

防止未來來源資料異常造成 OOM。

42. Build Pipeline 建議階段

Phase 1 — Inspector

先完成：

ZIP reader
nested ZIP reader
XML metadata parser
tupleList parser
inspect CLI

Acceptance：

可以直接：

gsi-dem inspect FG-GML-513462-DEM5A-20251208.zip

而且磁碟不產生 XML。

Phase 2 — Raster correctness

完成：

sequenceRule
startPoint
pixel ordering
coordinate mapping
PNG debug render

Acceptance：

真實 raster 與地形方向一致。

這個 Phase 完成前不要開始 bulk build。

Phase 3 — DEM5 merge

支援：

DEM5A
DEM5B
DEM5C

並完成：

A > B > C

pixel-level merge。

Phase 4 — DEM10

加入：

DEM10B

但保留為不同 resolution layer。

Phase 5 — Final tiling

將 merged raster 重新 tile 成：

256 × 256

並：

float32
 ↓ quantize
int16
 ↓ zstd
BLOB

Phase 6 — SQLite

完成：

metadata
elevation_tiles
source_tiles

與：

query(lat,lon)

Phase 7 — Validation

建立：

golden coordinates
visual raster checks
coverage report
source distribution report

Phase 8 — Android integration

Android 只負責：

SQLite
 ↓
tile cache
 ↓
zstd
 ↓
elevation lookup

不包含：

GML
ZIP
GSI mesh parser
merge logic

43. 第一版 Acceptance Criteria

完成以下條件才算 importer v1 完成：

可以直接讀 GSI ZIP，不將 XML 解壓到 filesystem。

支援 nested ZIP。

XML 使用 streaming parser。

正確解析 mesh/bounds/grid/source/date。

正確解析 Terrain / Sea / NoData。

驗證 tuple count 等於 grid sample count。

正確解析 GML traversal。

可以將真實 raster render 成 debug image。

DEM5A/5B/5C 可以 per-pixel merge。

Priority 為 5A > 5B > 5C。

DEM10B 保留為獨立 fallback layer。

Final elevation 使用 int16。

Tile 為 256×256。

Tile 使用 zstd。

SQLite 可以依 tile coordinate random access。

CLI 可以用 lat/lon query elevation。

Build 過程不會產生大量 XML temporary files。

Build memory 有上限，不隨 ZIP 數量線性增加。

有完整 build report。

有 golden coordinate regression tests。

44. 第一個實作任務

不要直接開始處理四國全部資料。

第一個 task：

輸入：
FG-GML-513462-DEM5A-20251208.zip

要求：
1. 不解壓 XML 到磁碟。
2. enumerate XML entries。
3. streaming parse metadata。
4. streaming parse tupleList。
5. 找出 sequenceRule/startPoint。
6. 產生 NormalizedRaster。
7. 驗證每張 raster sample count。
8. 選一張 raster render PNG。
9. 提供 lat/lon -> sample lookup。
10. 寫 unit/integration tests。

確認這個 PoC 正確後，才開始：

275 DEM5A
98 DEM5B
44 DEM5C
275 DEM10B

的 bulk processing。

45. 重要設計決策摘要

項目

決定

DEM1

不使用

DEM5 priority

5A > 5B > 5C

DEM10B

DEM5 fallback

原始資料

保留 ZIP

XML extraction

不落磁碟

Nested ZIP

memory buffer

XML parser

streaming

Intermediate elevation

float32

Final elevation

int16 / 1m

Sea

0m + mask/source

NoData

sentinel

Final tile

256×256

Projection

geographic fixed grid

Compression

zstd

Container

SQLite

Android lookup

lat/lon -> elevation

Source metadata

建議保留

DEM10 resampling

不預先假裝成 5m

Parallelism

bounded workers

DB writes

單 writer / controlled batching

46. Implementation Principle

整個工具應遵守：

GSI format
   ↓
Importer boundary
   ↓
Our own stable elevation format

Android App 永遠不應知道：

FG-GML
51346278
DEM XML
tupleList
sequenceRule

這些全部是 data build pipeline 的責任。

Android 只看到穩定介面：

latitude
longitude
    ↓
elevation
source/quality

如此未來即使：

GSI 格式改變

加入其他 elevation source

SQLite 改成 PMTiles / custom container

tile size 改變

encoding 改變

也不需要修改 App domain layer。
