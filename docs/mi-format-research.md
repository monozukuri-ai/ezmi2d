# MI / BI 形式調査

調査日: 2026-08-12

## 結論

このプロジェクトが対象とする MI は、現在の **PTC Creo Elements/Direct Drafting**、旧称 **HP ME10 / OneSpace Designer Drafting / CoCreate Drafting** の 2D 図面交換形式である。

- `.mi` は、行指向のテキスト形式である Model Interface Standard。
- `.bi` は、MI の圧縮形式。PTC の現行ヘルプは「Z-lib mechanism による圧縮」と説明している。
- MI 3.20 以降は UTF-8。旧版はロケール依存で、日本語環境のファイルは Shift_JIS 系を考慮する必要がある。
- 図面は、セクション、連番エンティティ、エンティティ番号への参照で構成される。単純な「座標列」ではなく、パーツ階層、プロパティ、注釈、寸法、ハッチ、フォント等を保持する。
- 完全なフィールド仕様は Web 公開ヘルプには見つからなかった。Drafting のインストール先に `locale/en/mi_interface/front.html` として同梱される。

公開サンプルとして、高広工業の製品ページから旧 HP ME10 5.02 / MI 2.10 の実ファイル 19 件と、対応する DXF 19 件を取得できるようにした。加えて、PTC Community の公開添付 bundle から、製品が生成した gzip 圧縮 MI 3.40 / UTF-8 とその正確な展開結果を取得・照合できるようにした。権利条件が再配布を明示的に許可していないため、実データは Git に含めず、固定 SHA-256 で取得する。

現時点で不足している重要資料は、(1) インストール版の完全な MI Interface Reference、(2) 同一図面を別々に保存した standalone `.mi` / `.bi` pair、(3) 世代別の圧縮 wrapper sample である。

## 1. 形式の同定

PTC の製品史では、ME10 は 1985 年の Rev.1.00 から始まり、Rev.11 で OneSpace Designer Drafting、Rev.16 で CoCreate Drafting、Rev.17 で Creo Elements/Direct Drafting に改称されている。Rev.15 で Unicode 対応が導入された。

PTC の現行ファイルブラウザは次を別形式として列挙している。

| 拡張子 | PTC の呼称 | 本調査での扱い |
|---|---|---|
| `.mi` または任意拡張子 | Model Interface Standard | 非圧縮 MI テキスト |
| `.bi` | Compressed MI | MI の圧縮エンベロープ |
| `.bdl` | Bundle | 2D と 3D を含み得る別コンテナ |

Creo Parametric 側のヘルプは `.mi` / `.bi` をそれぞれ ASCII / binary と表現するが、Drafting 側のより具体的な説明では `.bi` は Z-lib による Compressed MI である。本実装では「別のバイナリ図面文法」とは決めつけず、圧縮解除後に MI テキストを読む。取得した Creo bundle 内の製品生成 `am_2d_0.mi` は gzip wrapper だった。ただし、これだけから standalone `.bi` や全世代の wrapper も gzip だとは一般化しない。

`.mi` は他製品でも使われる拡張子である。たとえば mental ray の scene description も `.mi` を使うため、拡張子だけで判定してはならない。対象形式では `#~2` 等のセクションマーカー、`TC41:`、`PLAST:`、終端 `##~~` が強い識別材料になる。

## 2. 資料の信頼度

調査では、資料を次の順に扱う。

1. **PTC 現行ヘルプ**: 形式名、圧縮、文字コード、保存可能版、対応エンティティの根拠。
2. **Drafting 同梱 MI Interface Reference**: 個々のレコードとフィールドの正式仕様。現時点では所在のみ確認し、内容は未取得。
3. **Hewlett-Packard Journal (1987)**: MI の設計目的と内部データモデルの歴史的な一次資料。
4. **Bernard Saulme の旧形式解説**: MI 2.02 の完全な短い例を行単位で注釈した二次資料。現行版の仕様としては使わない。
5. **実サンプル**: 実装上の事実確認に使うが、サンプルに現れないレコードが存在しないとは判断しない。

PTC Community の 2015 年と 2023 年の回答はいずれも、正式なリファレンスの場所を次としている。

```text
C:\Program Files\PTC\Creo Elements\Direct Drafting <version>\locale\en\mi_interface\front.html
```

Drafting 19.0 では `Help > MI Interface` から開ける。参照先が相対リンクを使う可能性があるため、取得時は `front.html` 単体ではなく `mi_interface` ディレクトリ全体を保全する。

## 3. MI の論理構造

旧 MI 2.02 解説と今回取得した MI 2.10 の実ファイルは、次の構造で一致する。

| マーカー | 役割 | 備考 |
|---|---|---|
| `#~1` | info / start | 旧版では省略可能。現行ローダは `LANG:`、`ENCODING:` 等をここから読む。取得サンプルでは省略。 |
| `#~2` | table of contents | セクションの先頭エンティティ番号や、パーツ内・ファイル全体の最終番号を記録。 |
| `#~3` | global | 図面名、生成日時、生成システム、MI 版、範囲、尺度、用紙、単位、精度、変換行列等。 |
| `#~41` | simple properties | 例: `PSTAT`、`ASSP`。 |
| `#~42` | composite properties | legacy 19 件には出現しない。MI 3.40 sample では `DTV` 等を保持。 |
| `#~5` | assembly hierarchy | `ASSE` により TOP と下位パーツを記述。 |
| `#~6` | part definition | パーツごとに繰り返され、その後に当該パーツの各サブセクションが続く。 |
| `#~61` | geometry points | `P` が座標を保持する。 |
| `#~62` | geometry elements | `LIN`、`ARC`、`FIL`、`BSPL`、`CIR` 等。座標そのものではなく `P` のエンティティ番号を参照する。 |
| `#~63` | composite geometry | 取得した 19 件には出現しない。 |
| `#~71` | annotation elements | 取得サンプルでは空。 |
| `#~72` | composite annotation | 取得サンプルでは `TEX` がここにある。 |
| `#~81` | faces | 旧形式解説に記載。取得サンプルには出現しない。 |
| `#~82` | modern structure / symbol | MI 3.40 sample で `SYML` 等を確認。 |
| `|~` | entity terminator | 1 エンティティの終端。 |
| `##~~` | file terminator | ファイル終端。 |

### 3.1 Table of contents

実サンプル `S40` の冒頭は、概略として次の意味を持つ。

```text
#~2
2
TC41:1
TC5:3
Top
4
TC61:4
TC62:436
TC72:731
PLAST:733
LAST:733
```

- ファイル全体側では section 41 が entity 1、section 5 が entity 3 から始まる。
- `Top` パーツでは section 61 が entity 4、section 62 が 436、section 72 が 731 から始まる。
- `PLAST` はそのパーツの最終 entity、`LAST` はファイル全体の最終 entity を示す。

`TC` の件数行やパーツごとの繰り返しを含む正確な文法は、正式リファレンス取得後に確定する。

### 3.2 エンティティと参照

各エンティティにはファイル内の連番があり、他のエンティティはその番号を pointer として参照する。たとえば取得サンプルでは次が確認できる。

- `P`: entity number、X、Y。
- `LIN`: 表示属性、property pointer、始点 `P`、終点 `P`。
- `ARC`: 表示属性、property pointer、中心・始点・終点の `P`、向き。
- `CIR`: 表示属性、property pointer、中心 `P`、円周上 `P`。
- `TEX`: 表示属性、変換、フォント、文字寸法、文字列等、多数の位置依存フィールド。

したがってパーサは、読みながら参照先オブジェクトへ直接変換するより、まず entity number と生の参照番号を保持し、読み終えた後に解決する二段階方式が安全である。壊れた参照、前方参照、未知エンティティを診断できるようにする。

### 3.3 保持される CAD 意味論

PTC の Creo Parametric インポート仕様から、MI / BI が少なくとも次を表現できることを確認した。

- line、arc、circle、spline を含む 2D construction geometry
- linear、angular、radial、diameter、ordinate、arc dimension
- leader 付き / なし note
- annotation view、detail view、general view、複数 sheet
- Drafting part、symbol part、part hierarchy
- color、layer、linetype、text font、hatch font
- hatch を論理要素として保持
- Unicode、TrueType、multi-line text

さらに PTC の DXF 変換注意事項では、MI の 1 entity が複数 layer に所属できること、shared part の変換、寸法の prefix / postfix / tolerance、独自 symbol font 等が説明されている。ezdxf 風 API を設計するときも、DXF の制約へ早期に丸めず MI 固有の意味をモデル側に残す必要がある。

## 4. バージョンと文字コード

### 4.1 確認できたルール

- PTC は MI 3.20 を UTF-8 と明記している。
- MI 3.20 より前は保存時ロケールに依存する。
- ローダは `#~1` の encoding 情報を使用する。
- encoding 情報がない旧 MI は、通常 ROMAN8、日本語ロケールでは SJIS として扱われる。
- MI 2.90 より前で encoding 情報がないファイルは、原則として作成時と同じロケールでのみ正しく読める。
- PTC の修復例は、旧日本語 MI の先頭へ次を追加する。

```text
#~1
ENCODING:SJIS
```

- Unicode 化は CoCreate Drafting 15.00 / 2007 で行われた。
- 旧 symbol escape は Unicode Private Use Area へ対応付けられる。
  - `15#XY#16` → `0xE000 + XY`
  - `30#XY#31` → `0xE100 + XY`

PTC 20.8 の保存 UI は MI 3.80、3.70、3.60、3.50、3.40、3.30、3.20 等を明示的に選択できる。旧版互換は実際の要件になる。

### 4.2 パーサへの含意

1. 最初から Unicode 文字列として開かず、bytes として読む。
2. `.bi` なら圧縮解除してから、同じ MI byte decoder へ渡す。
3. ユーザーの明示 override、UTF-8 BOM、MI version 3.20 以上、旧版の `#~1`
   `ENCODING:` 宣言の順に判定する。
4. 宣言のない旧版だけを既知 text field から保守的に推定し、推定した事実を診断へ残す。
5. UTF-8、CP932 互換 Shift_JIS、HP Roman-8 を strict decode し、曖昧な single-byte
   データを推測で Roman-8 と決めない。
6. decode error を置換して消さず、元 bytes と正確な byte span を診断へ残す。
7. 改行は取得サンプルの CRLF だけを前提にせず、CRLF / LF / CR を受理する。

Phase 3 ではこの順序を Rust core に実装した。Python の `read()` / `readfile()` は
`encoding=` override を受け取り、`Document.encoding_info` に canonical name、判定元、
元の宣言名を保持する。各 `TextValue` は raw bytes、strict decode 結果、使用 encoding を
分離するため、明示されなかった値と置換済み文字列を混同しない。

## 5. compressed MI と Phase 4

PTC は `.bi` を **Compressed MI**、圧縮方式を **Z-lib mechanism** と説明している。現行 Creo Parametric は `.bi` を読み込める一方、Drafting 付属の MI↔DXF/DWG translator は compressed MI を受け付けない。

Phase 4 では PTC Community に公開された、投稿者が Creo 18.1 で作成したと説明する bundle を取得した。その 2D member は `am_2d_0.mi` という名前だが、内容は次の gzip stream である。

| 項目 | 検証値 |
|---|---|
| magic | `1f 8b 08` |
| 圧縮サイズ | 87,506 bytes |
| 圧縮 SHA-256 | `60303e5f6dd38f434fd20b20798b3a9d3d9dfcb0e9883015119db6b3d1b49ecc` |
| 展開サイズ | 393,805 bytes |
| 展開 SHA-256 | `3bb45897b8cdbb9bc0e82048af65677274548002234c4a0190b4f0f14a1d1d65` |
| 論理形式 | MI 3.40、`#~1`、`ENCODING:UTF-8`、CRLF |
| 構造 | 55,160 lines、144 sections、4,527 records |

Rust core は magic に基づき単一 gzip member を streaming 展開し、その論理 bytes を Phase 1 scanner と Phase 3 semantic decoder の同じ入口へ渡す。Python の `RawScan.source_bytes` と全 span は論理 MI を参照し、呼出元が渡した圧縮 bytes は `container_bytes` として別に保持する。次の制限を独立に適用する。

- `max_file_size`: 元コンテナの最大 byte 数
- `max_decompressed_size`: 展開後 MI の最大 byte 数
- `max_compression_ratio`: 展開後 / コンテナの最大比率
- gzip checksum / truncation error、trailing data、連結 member を拒否

Phase 4 時点では、実製品データの圧縮入力と展開結果について論理 bytes、global metadata、25 parts、4,499 addressable entities、128 graphic entities、35 texts、semantic diagnostics が一致した。Phase 5 の decoder 拡張後も同値性は維持され、typed graphic は 216 件（うち `BSPL` 88 件）、typed annotation は 88 件になった。合成 gzip は container mechanics と異常系テストにだけ使い、形式同定の根拠にはしていない。

### 5.1 Phase 5 semantic expansion

Phase 5 では、正式な field 名が得られていない部分を raw bytes のまま残しつつ、実コーパスで境界を検証できたレコードを typed model へ昇格した。

- legacy `FIL` 353 件は `ARC` と同じ中心・始点・終点・向きの layout として解釈し、対応 DXF の追加 `ARC` 353 件と multiset が全件一致した。
- `BSPL` は entity ID 後の可変 prefix を走査し、order、2 個の未命名 definition value、parameter maximum、始点・終点、control point IDs、knot vector、補間 sample の自己整合する唯一の layout を選ぶ。legacy 6 件と MI 3.40 の 88 件すべてで layout は一意だった。
- legacy `BSPL` の保存 sample 36 点は De Boor 評価と最大約 `6.4e-14` で一致し、対応 DXF の `POLYLINE` 全頂点も最大約 `1.5e-13` で曲線上に一致した。
- section 72 の `DANG` / `DCHMF` / `DDIA` / `DRAD` / `DSGL`、section 42 の `DTV`、`LED`、`HAT`、`SYML` を record family ごとの型にした。位置依存 field は `values` と元 `RawRecord` で保持し、未検証の意味名を付けていない。
- `ASSE` の可変 property prefix、子 assembly ID、member IDs、serialized 3x3 transform、part 対応を復元した。製品サンプルの 25 parts / 24 instances は単一 root に解決され、`DOCU_SHEET` association から sheet part 1 件を同定した。
- 自作 fixture は root → 2 sheets → shared leaf という構造を持ち、nested/shared part、異なる instance transform、multiple sheets を regression test にする。

各 Phase 5 record family には正常 fixture と短縮・破損 fixture があり、破損時も `UnsupportedEntity.raw_record` から payload を取得できる。つまり typed decoder の失敗によって addressable record を黙って捨てない。

このサンプルは bundle 内の製品生成圧縮 MI であり、別名保存した standalone `.bi` ではない。したがって現実装が保証する範囲は **gzip magic を持ち、展開後が MI text である入力** である。zlib wrapper と ZIP signature は検出して unsupported error にし、古い UNIX compress 等の世代差も未対応とする。同一図面を Drafting から standalone `.mi` / `.bi` へ保存する相互運用試験は引き続き必要である。

## 6. 取得したサンプル corpus

### 6.1 高広工業 SoarerDex

高広工業の SoarerDex CAD データページは、ME10 用 MI ファイルの個別・一括ダウンロードを提供している。`scripts/fetch_external_samples.sh` は一括 MI と対応 DXF を HTTPS で取得し、SHA-256 を照合する。

検証結果:

| 項目 | 結果 |
|---|---|
| MI ファイル数 | 19 |
| 対応 DXF | 19（basename が 1 対 1 で一致） |
| MI 合計サイズ | 671,852 bytes |
| producer | `HP ME10 Rev. 05.02A 30-Jan-93` |
| MI version | 2.10 |
| ファイル名 | `F100` 等、拡張子なし |
| 改行 | 全件 CRLF |
| 開始 / 終端 | 全件 `#~2` / `##~~` |
| section | 全件 `~2`, `~3`, `~41`, `~5`, `~6`, `~61`, `~62`, `~71`, `~72` |
| 文字 | 全件に日本語あり。CP932 strict decode 成功。encoding 宣言はない |
| geometry | 合計 `P` 10,166、`LIN` 4,030、`ARC` 1,059、`CIR` 1,196、`FIL` 353、`BSPL` 6 |
| annotation | 合計 `TEX` 57 |

MI archive:

```text
URL: https://www.takahiro.co.jp/en/product/cad/me10/index.zip
SHA-256: 5b56a6777e8bc6c5023c31e3ee503f67d7fdd4a3cb9e35e79c284bb977c6a30d
```

DXF archive:

```text
URL: https://www.takahiro.co.jp/en/product/cad/dxf/index.zip
SHA-256: cd3fdd2097f3b89e15669878ba0d8000ccfcd204e4f880987965b2efc4bda65a
```

この corpus の利点は、実運用で重要な「拡張子なし」「`#~1` なし」「旧版」「日本語」「MI と DXF の対」が揃うことにある。一方、同じ系統の機械図面だけであり、dimension、hatch、複雑な spline、複雑な part tree、modern UTF-8、`.bi` の十分なカバレッジにはならない。

Phase 2 実装後の全件 regression では、10,166 個の `P` と 6,285 個の
`LIN` / `ARC` / `CIR` がすべて参照解決でき、property pointer に未解決はなかった。
Phase 3 では、宣言のない全 19 件を既知文字 field から Shift_JIS と判定し、57 個の
`TEX` を置換文字なしで strict decode できた。対応 DXF を独立な相互運用 oracle として、
次を小数点以下 7 桁へ丸めた multiset で照合した。

- `LIN` と DXF `LINE`: 始点・終点および件数が全件一致。
- `CIR` と DXF `CIRCLE`: 中心・半径および件数が全件一致。
- MI `ARC`: 中心・始点・終点が DXF `ARC` の部分集合として全件一致。
- DXF 側の追加 `ARC` 353 件は MI `FIL` 353 件とファイルごとの件数が一致。
- MI `BSPL` 6 件と DXF `POLYLINE` 6 件がファイルごとに一致。
- MI `TEX` 57 件と DXF `TEXT` 57 件で、CP932 復元後の文字列、文字高さ、挿入位置が
  全件一致。取得 corpus の配置関係は DXF `(x, y) = (origin.x, origin.y - height / 2)` だった。
- global section の drawing extents と DXF `$EXTMIN` / `$EXTMAX` が全件一致。

これは取得 corpus に対する positional layout の強い裏付けだが、MI Interface Reference
の代用ではない。Phase 5 では `FIL` と `BSPL` を上記の検証済み範囲で typed 化した。`TEX` は全 57 件で共通する
30 field layout のうち、共通表示値、property pointer、fields 8..16 の 3x3 serialized
transform、その translation entries、field 19 の font name、fields 22..23 の size、
field 28 の content のみ typed API にした。他の field は speculative name を付けず、
`Text.values` と元 `RawRecord` へ残している。回転、alignment、複数行、symbol escape は
この corpus だけでは検証できていない。

### 6.2 PTC Community Creo bundle

公開投稿の添付 `1_09_04_010_MANDREL.zip` は `.bdl` を含み、その bundle は product-generated gzip 圧縮 `am_2d_0.mi` を含む。取得スクリプトは outer ZIP、BDL、圧縮 member、展開 MI の 4 段階すべてを SHA-256 で固定する。

```text
Attachment SHA-256: e1e5ee6c0c63dab1bba8dcf7780645398da70c59a230a41ac20c363e3a6431ec
Bundle SHA-256:     63b2952002451d0693b9db56e466dce1f09810528d92c7e28722afcf422a7b0d
```

MI 3.40 / UTF-8、複数 part、dimension 系を含むため、modern product fixture として使える。Phase 5 では 88 `BSPL`、46 dimension、10 `DTV`、7 `LED`、9 `HAT`、16 `SYML` と 25-part hierarchy を typed 化した。一方、modern `LIN` / `ARC` / `CIR` / 一部 `TEX` 等の version-specific layout は未対応であり、semantic diagnostic は残る。圧縮／展開入力で完全一致することを検証しているが、既知 subset 以上を decode 済みとは解釈しない。

### 6.3 権利上の扱い

配布元ページはダウンロードして利用するよう案内しているが、サイトには All Rights Reserved とあり、データの再配布ライセンスは確認できなかった。そのため本リポジトリでは次を採用する。

- URL、checksum、検証 metadata、取得スクリプトのみ Git 管理する。
- 実ファイルは `samples/external/` に取得し、`.gitignore` で除外する。
- CI で無断再配布しない。ネットワーク fixture として使う場合も配布元条件を再確認する。
- 将来、再配布可能な最小 fixture は自作するか、権利者から許諾を得る。

詳細は `samples/README.md` と `samples/manifest.toml` を参照する。

### 6.4 PTC 同梱サンプル

PTC の 2D Access manual は、インストール物に tutorial 用 `example.mi` が含まれると明記している。別の公式 tutorial には `pd_demos/demo05.mi` 等の名前も現れる。2D Access 自体は MI 図面の表示・計測用 read-only oracle としても有用である。

これらは出所の明確な相互運用 fixture 候補だが、今回の Linux 環境には PTC 製品がなく、ファイル本体は取得できていない。PTC の 2D / 3D Access 取得手順記事は全文閲覧に eSupport sign-in を要求し、Modeling Express の無償 Windows installer も利用条件への同意とアカウント activation を要求するため、ここでは代理同意や installer 取得を行っていない。利用者自身で条件を確認した上で、インストール物からローカル検証用に取得する。

## 7. 公開実装の探索結果

2026-08-12 時点で、GitHub の repository / code search と一般 Web 検索を `ME10`, `CoCreate Drafting`, `Creo Elements/Direct Drafting`, `TC41`, `PLAST`, `#~62` 等で行ったが、MI を読んで公開 API を提供する再利用可能な OSS parser は確認できなかった。これは探索範囲内の結果であり、存在しないことの証明ではない。

一方、商用 CAD / viewer の対応例と PTC 自身の converter は確認できる。相互運用 oracle としては有用だが、公開ソースの基礎実装として利用できるものではない。

## 8. 実装前に揃える最小 fixture matrix

| fixture | 必須内容 | 状態 |
|---|---|---|
| legacy text MI | MI 2.10、Shift_JIS 系、拡張子なし、line/arc/circle/text | 19 件取得済み |
| matching DXF | legacy MI と basename が一致する DXF | 19 件取得済み |
| modern text MI | MI 3.20 以上、`#~1`、UTF-8、日本語と欧文 | 製品生成 MI 3.40 を 1 件取得。文字種 coverage は未監査 |
| compressed MI | 同一論理図面の圧縮／展開 pair | bundle 内の製品生成 gzip member を取得・照合済み。standalone `.bi` pair は未取得 |
| geometry coverage | legacy `FIL` 353、legacy `BSPL` 6、modern `BSPL` 88 を取得・typed 検証済み。composite / construction geometry は未対応 |
| structure coverage | 製品 sample の nested/shared/transformed 25-part tree を取得。multiple-sheet は自作 fixture で検証 |
| annotation coverage | angular/radial/diameter/single/chamfer dimension、DTV、leader、hatch、symbol を製品 sample で取得。全 variant と field semantics は未確定 |
| document coverage | 製品 sample の 1 sheet / views と、自作 fixture の 2 sheets を検証。embedded font は未取得 |
| malformed corpus | broken pointer、wrong type、duplicate ID、non-finite coordinate、invalid text byte、missing `|~` / `##~~`、truncation | 最小 fixture を自作済み |

PTC 環境を利用できる場合は、同じ小図面を MI 3.20、最新 MI、Compressed MI で保存して pair を作る。図形だけでなく、日本語 text、dimension tolerance、hatch、nested part を 1 つずつ明示的に含める。

## 9. 推奨する初期実装境界

調査結果から、最初の実装は次の順が安全である。

1. **byte source / format sniffing**: extension に依存せず、非圧縮 MI と compressed MI を分離する。
2. **encoding detection**: `#~1`、MI version、明示 override を扱い、元 bytes を保持する。
3. **lossless section reader**: 空行と順序を保ち、未知 section / entity を raw record として残す。
4. **entity index**: entity number の一意性、TC / PLAST / LAST、pointer、terminator を検証する。
5. **semantic model**: properties、parts、points、geometry、annotation の順に typed object へ昇格する。
6. **public API**: ezdxf と同様に document / modelspace / entities の探索を提供しつつ、MI 固有の part tree と raw fallback を失わない。
7. **writer / round trip**: reader が安定してから追加し、未知 record の保持と PTC 製品での再読込を gate にする。

正式リファレンス取得前に、`TEX` の未検証 field や dimension の位置依存フィールドを
推測で固定 API にしないことが重要である。

## 10. 参照資料

### PTC / HP 一次資料

- [PTC: MI file format (encoding)](https://support.ptc.com/help/creo/ced_drafting/r20.8.0.0/en/ced_drafting/2d_access_win/MI_file_format.html)
- [PTC: Limitations for loading pre-2.90 files](https://support.ptc.com/help/creo/ced_drafting/r20.8.0.0/en/ced_drafting/user_classic/Limitations_2.html)
- [PTC: Opening a Drawing File](https://support.ptc.com/help/creo/ced_drafting/r20.8.0.0/en/ced_drafting/user_fluentui/Opening_a_Drawing_File_Using_the_Drafting_File_Browser.html)
- [PTC: Saving a Drawing File](https://support.ptc.com/help/creo/ced_drafting/r20.8.0.0/en/ced_drafting/user_win/Saving_a_Drawing_File_via_the_Drafting_File_Browser.html)
- [PTC: Importing Creo Elements/Direct Drawing Files](https://support.ptc.com/help/creo/creo_pma/r12/usascii/data_exchange/interface/About_Importing_CED_MI_Drawings_to_Creo.html)
- [PTC: MI to DXF/DWG translator limitations](https://support.ptc.com/help/creo/ced_drafting/r20.8.0.0/de/ced_drafting/dxftrans/Hints_and_Tips_for_Translating_MI_to_DXF_DWG.html)
- [PTC: 2D Access manual (Unicode and `example.mi`)](https://support.ptc.com/help/creo/ced_drafting/r20.6.0.0/de/ced_drafting/baggage/2d_access_win.pdf)
- [PTC: About Creo Elements/Direct 2D Access](https://support.ptc.com/help/creo/ced_drafting/r20.9.0.0/en/ced_drafting/2d_access_win/About_2D_Access.html)
- [PTC: Downloading 2D Access / 3D Access (sign-in required)](https://www.ptc.com/en/support/article/CS379989)
- [PTC 日本語ブログ: ME10 から Creo までの歴史](https://www.ptc.com/ja/blogs/cad/history-of-creo-elements-direct-non-history-jp)
- [Hewlett-Packard Journal, May 1987](https://www.worldradiohistory.com/Archive-Company-Publications/HP-Journal/80s/HPJ-1987-05.pdf)

### 仕様所在と旧形式の補助資料

- [PTC Community (2023): MI specification location](https://community.ptc.com/drafting-324/documentation-file-specification-mi-cad-files-143164)
- [PTC Community (2015): Help > MI Interface](https://community.ptc.com/drafting-324/where-can-i-find-manuals-for-mi-format-storage-14435)
- [Bernard Saulme: Informations sur les fichiers MI](https://softs.saulme.fr/download/download.php?d=mi.pdf&h=application%2Fpdf)

### サンプル

- [高広工業: SoarerDex CAD データ](https://www.takahiro.co.jp/product/sd_cad.html)
- [PTC Community: Creo bundle attachment の投稿](https://community.ptc.com/3d-part-assembly-design-327/error-opening-bdl-file-files-does-not-contain-a-valid-drawing-80415)
- [CoCreate User Forum archive: legacy compressed MI variants](https://web.archive.org/web/20200101000000id_/http://www.cocreateusers.org/forum/archive/index.php/t-4848.html)

## 11. 調査上の未確定事項

- 現行 MI Interface Reference の全 entity / field 定義と version history
- standalone `.bi` と bundle 内圧縮 MI の wrapper 同一性、および世代別 wrapper 差
- embedded font の格納方法と、文字列以外に現れる非テキスト payload
- MI 3.20〜3.80 の section / entity 追加差分
- DTV / dimension / ASSE の未命名 field、associativity、shared instance の正式 semantics と version 差
- PTC Drafting / 2D Access を使った読み込みと round-trip の実機検証

これらは parser の対応範囲を明示するための backlog であり、推測で埋めない。
