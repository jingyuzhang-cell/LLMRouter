from scripts.run_offline_knn_baseline import stratified_split


def test_strict_split_is_disjoint_exact_and_keeps_rare_label_in_train():
    labels={f't{i:03d}':('rare' if i==0 else 'a' if i<61 else 'b') for i in range(100)}
    split=stratified_split([{'id':x} for x in labels],labels)
    assert [len(split[x]) for x in ('train','validation','test')]==[60,20,20]
    assert not (set(split['train'])&set(split['validation']))
    assert not (set(split['train'])&set(split['test']))
    assert not (set(split['validation'])&set(split['test']))
    assert 't000' in split['train']
