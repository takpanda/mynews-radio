## 台本構造スキャン

`app.batch.structure_scan.scan_script_structure()` は、生成後・レビュー後の台本を対象に、前後関係から要確認候補を抽出します。

- `STRUCTURE_RESPONSE_WITHOUT_QUESTION`: 「そうです」「そうなんです」「そうですね」「なるほど」「たしかに」等で始まる台詞について、同じ記事ブロック内の直前4行に問い（`?`、`ですか`、`でしょうか` 等）がない場合。
- `STRUCTURE_ADJACENT_NEWS_SIMILAR`: 隣接するニュースのタイトル・要約・カテゴリから抽出したキーワードが重なる、またはカテゴリが同じ場合。候補であり、同カテゴリだけでは同一ニュースとは確定しません。
- `STRUCTURE_DISCUSSION_TARGET_MISMATCH`: 討論対象の記事IDが直前ニュースの記事ID、またはNarrative Arcの選定ID（指定時）と異なる場合。

レビュー工程では台本と同じディレクトリの `summaries.json` を読み込み、隣接ニュースの検査にも利用します。生成時にNarrative Arcの `discussion_article_id` が得られた場合は `script.json` に保存し、レビュー後も選定IDとの不一致を検査します。`summaries.json` がない入力（単一記事コメンタリー等）は、利用可能な検査だけを警告として実行します。

いずれも初期導入では警告のみで、再生成・ジョブ失敗・公開停止は行いません。レビュー担当者は `script.json` の該当行、`summaries.json` のタイトル・要約・カテゴリ、Arcの `discussion_article_id` を突き合わせ、誤検出なら理由を記録し、真の不整合なら手動で再生成または修正を判断してください。`「〜ですね」` が文中・末尾に現れるだけの場合は応答形とみなしません。
