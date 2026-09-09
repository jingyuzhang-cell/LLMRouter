# Pilot暴露审计（仅ID/请求匹配）

已知pilot query：500；与train/validation/test重叠：{'train': 354, 'validation': 65, 'test': 81}

原test中排除已知pilot后剩669题。此名单只用于审查，没有改变原split，也没有把剩余题自动认证为独立holdout。

原750题test不能整体称为未触碰。继续训练可以服务开发验证；正式独立确认需先处理这个已知暴露问题。

没有读取或汇总新的测试质量，也没有因表现删除测试题。
