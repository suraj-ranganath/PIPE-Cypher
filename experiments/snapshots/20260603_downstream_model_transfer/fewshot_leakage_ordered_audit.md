# Few-Shot Leakage Audit

- Train examples: `2408`
- Test examples: `296`
- Selection rows: `296`
- Exact train/test question overlap: `0` (0.000)
- Train/test query-signature overlap: `295` (0.997)
- Selected demonstrations with query-signature matches: `1314` (0.888)
- Selected demonstrations above question-similarity threshold: `581` (0.393)
- Mean / max selected question similarity: `0.846` / `0.941`

## Risk Examples

- `pc_018770ec18ebcb5f` finbench/boolean_existence mode=ordered_same_category selected=pc_00c0d254748f7ec9,pc_024198652a5f23e5,pc_087cc0a0c09cb55c,pc_0a68fd192d6c2ec1,pc_0be15b8c6e1f2121 max_sim=0.929 signature_match=true
- `pc_048ca1cefb04b7af` snb/simple_aggregation mode=ordered_same_category selected=pc_024b8bc487f62d20,pc_062796241da85b72,pc_06bbb12128be1a77,pc_13198046bd81ff3e,pc_1a51d93ac07cd799 max_sim=0.833 signature_match=true
- `pc_04cb83fefb1ea753` finbench/complex_retrieval mode=ordered_same_category selected=pc_01aed23f072ad9b7,pc_0244b25432e91648,pc_0316587e27762bd9,pc_037ac451fe2ba969,pc_04a44fb93b6d390c max_sim=0.917 signature_match=true
- `pc_04dec9b06f33bb1b` finbench/simple_aggregation mode=ordered_same_category selected=pc_00f2dee48bfeeeec,pc_012eef6d90cfcdb9,pc_01f681ad0df8220c,pc_032aabcb1c3dae9d,pc_03ce568f5b33b016 max_sim=0.875 signature_match=true
- `pc_062b0dd117feae38` finbench/simple_aggregation mode=ordered_same_category selected=pc_00f2dee48bfeeeec,pc_012eef6d90cfcdb9,pc_01f681ad0df8220c,pc_032aabcb1c3dae9d,pc_03ce568f5b33b016 max_sim=0.875 signature_match=true
- `pc_06e9d06373b0206f` snb/ranking_topk mode=ordered_same_category selected=pc_038d783b25839570,pc_04d812fc1e3fe67b,pc_07503d6a6dc50fe9,pc_0a13bbb9b77886c0,pc_0c02c1a5dd7884d9 max_sim=0.900 signature_match=true
- `pc_08698690e405c0ec` snb/boolean_existence mode=ordered_same_category selected=pc_06a55c94223666d9,pc_0767a467be3f0950,pc_0a400c1f352bb11e,pc_0cd9802e59c50296,pc_0e25f4ffdff65daf max_sim=0.875 signature_match=true
- `pc_089979dae2cb414a` finbench/negation_difference mode=ordered_same_category selected=pc_00a8253758683aa8,pc_00ecf66bde496d01,pc_017dae00b0333071,pc_02bdfd7a16663102,pc_04b0340fa4f6e1d3 max_sim=0.909 signature_match=true
- `pc_0901053eaf377f7b` snb/path_temporal mode=ordered_same_category selected=pc_00d2146cfc2b9e7f,pc_043f7738105b816e,pc_04e62ac53c48f09f,pc_052f48ad24c6ecf3,pc_0c13c45074224772 max_sim=0.917 signature_match=true
- `pc_0955f1fe2a9aa5d4` finbench/simple_retrieval mode=ordered_same_category selected=pc_00288c6fa844b82b,pc_0099732c91892e17,pc_01c41b5a81fcbf89,pc_01d6c7256c012057,pc_046a2264dc40660f max_sim=0.857 signature_match=true
- `pc_0aed56072386636e` snb/complex_retrieval mode=ordered_same_category selected=pc_06656160e11b0a87,pc_07a7c6f75f36cfc8,pc_07f03f6decb76e77,pc_092dc0669de7f243,pc_0f6f772d891c8a50 max_sim=0.735 signature_match=true
- `pc_0bb639eedae65f81` finbench/boolean_existence mode=ordered_same_category selected=pc_00c0d254748f7ec9,pc_024198652a5f23e5,pc_087cc0a0c09cb55c,pc_0a68fd192d6c2ec1,pc_0be15b8c6e1f2121 max_sim=0.929 signature_match=true
- `pc_0d63dc59098d1e8e` finbench/complex_aggregation mode=ordered_same_category selected=pc_00191b32d4f9a0d2,pc_057a57d8fff0529c,pc_0785ae40acbbf0a2,pc_078ec937da295414,pc_09fa6d6fc0606035 max_sim=0.917 signature_match=true
- `pc_0f5b42c3ca751388` finbench/complex_aggregation mode=ordered_same_category selected=pc_00191b32d4f9a0d2,pc_057a57d8fff0529c,pc_0785ae40acbbf0a2,pc_078ec937da295414,pc_09fa6d6fc0606035 max_sim=0.917 signature_match=true
- `pc_10398d5ecca9c6c0` snb/simple_aggregation mode=ordered_same_category selected=pc_024b8bc487f62d20,pc_062796241da85b72,pc_06bbb12128be1a77,pc_13198046bd81ff3e,pc_1a51d93ac07cd799 max_sim=0.833 signature_match=true
- `pc_115a40ff9a98ba8c` finbench/simple_aggregation mode=ordered_same_category selected=pc_00f2dee48bfeeeec,pc_012eef6d90cfcdb9,pc_01f681ad0df8220c,pc_032aabcb1c3dae9d,pc_03ce568f5b33b016 max_sim=0.875 signature_match=true
- `pc_11b505ff8c8b5ba3` finbench/complex_aggregation mode=ordered_same_category selected=pc_00191b32d4f9a0d2,pc_057a57d8fff0529c,pc_0785ae40acbbf0a2,pc_078ec937da295414,pc_09fa6d6fc0606035 max_sim=0.917 signature_match=true
- `pc_12ac125e4f8a5c59` snb/complex_retrieval mode=ordered_same_category selected=pc_06656160e11b0a87,pc_07a7c6f75f36cfc8,pc_07f03f6decb76e77,pc_092dc0669de7f243,pc_0f6f772d891c8a50 max_sim=0.900 signature_match=true
- `pc_1383f998121a6290` finbench/path_temporal mode=ordered_same_category selected=pc_00cfe6136bcf6427,pc_0265ea401b1e569c,pc_02faf97f3243891d,pc_03e5f605ac0e73b3,pc_04ff3bf2354bd6c9 max_sim=0.941 signature_match=true
- `pc_141bd0915a8a8054` finbench/negation_difference mode=ordered_same_category selected=pc_00a8253758683aa8,pc_00ecf66bde496d01,pc_017dae00b0333071,pc_02bdfd7a16663102,pc_04b0340fa4f6e1d3 max_sim=0.909 signature_match=true
