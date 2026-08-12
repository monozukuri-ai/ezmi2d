# External MI samples

公開配布元から検証済み corpus を取得する。

```bash
./scripts/fetch_external_samples.sh
```

必要なコマンドは `curl`, `gzip`, `sha256sum`, `unzip` である。取得先は次の通り。

```text
samples/external/takahiro-soarerdex/
├── archives/
├── dxf/
├── mi/
└── SHA256SUMS

samples/external/ptc-community-mandrel/
├── archives/
├── compressed/
├── mi/
└── SHA256SUMS
```

`mi/` 内のファイルは配布元の名前を維持するため、`.mi` 拡張子を持たない。内容は HP ME10 の MI 2.10 である。`dxf/` には同じ basename の比較用 DXF が入る。

`ptc-community-mandrel` は公開 PTC Community 添付の Creo bundle から取得する。
`compressed/am_2d_0.mi` は製品が bundle に格納した gzip 圧縮 MI、`mi/am_2d_0.mi` は
その正確な展開結果である。前者は standalone `.bi` というファイル名ではないため、全世代の
`.bi` が同じ wrapper だという証拠には使わない。Phase 4 では、この実データについて両入力の
raw / semantic model が一致することを regression test にしている。Phase 5 ではさらに、
88 `BSPL`、dimension / `DTV` / `LED` / `HAT` / `SYML`、25-part hierarchy、sheet association
についても圧縮・展開結果が一致することを検証する。

外部ファイルは Git に含めない。どちらの corpus も再配布ライセンスを確認できていないため、
利用時は各配布元の条件を確認すること。

固定 URL、archive checksum、内容の検証結果は `manifest.toml`、形式調査は `../docs/mi-format-research.md` を参照する。

MI の semantic decode と、対応 DXF に対する geometry および `TEX` の
文字列・挿入位置・高さの比較は、開発用・corpus 用の optional dependency を入れて実行する。
`FIL` は DXF の追加 `ARC` と中心・始点・終点を照合し、`BSPL` は保存された補間点と
対応 `POLYLINE` の全頂点を De Boor 評価した曲線へ照合する。

```bash
uv sync --locked --extra dev --extra corpus
uv run --extra corpus pytest tests/python/test_external_corpus.py
```
