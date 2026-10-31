#!/usr/bin/env python3
"""Resolve optional book parameters. No image generation or photo interpretation."""
import argparse
import copy
import json
import random
import secrets
from pathlib import Path

DEFAULT_PAGE_COUNT = 32
MIN_PAGE_COUNT = 30

ALIASES = {
    '角色': 'characters', '角色参考': 'character_refs', '场景': 'scene',
    '主题': 'theme', '训练重点': 'learning_focus', '年龄': 'age',
    '难度': 'difficulty', '已有能力': 'abilities', '风格': 'style',
    '语言': 'language', '总页数': 'page_count', '册数': 'book_count',
    '版式': 'format', '输出目录': 'output_dir', '随机种子': 'seed',
    '避免内容': 'avoid', '其他约束': 'constraints',
}
WORLDS = {
    '森林邮局': ['树屋邮局', '林间驿站', '松果广场'],
    '海洋探索': ['潮池观察站', '珊瑚邮局', '海底花园'],
    '太空旅行': ['月球温室', '星际车站', '飞船仓库'],
    '社区合作': ['社区花园', '街角书屋', '邻里厨房'],
    '四季自然': ['秋日果园', '春日花圃', '雨后草地'],
    '奇妙交通': ['小镇车站', '河边码头', '山间缆车站'],
    '日常发现': ['玩具房', '家庭厨房', '阳台花园'],
    '小小建造师': ['积木工坊', '河畔营地', '树屋工地'],
}
CHARACTERS = ['戴圆眼镜的小水獭', '背蓝色布包的小刺猬', '穿黄雨衣的小兔',
              '系绿围巾的小狐狸', '戴条纹帽的小熊', '穿背带裤的小象']
METHODS = {
    '观察': [('轮廓匹配', '指一指'), ('比较局部特征', '说出线索')],
    '分类': [('按单属性分组', '分一分'), ('换一种分类规则', '重新分组')],
    '数感': [('一一对应', '逐个配对'), ('比较多少', '说明比较方法')],
    '空间': [('位置关系', '指一指'), ('按标记选择路线', '用手指走路线')],
    '规律': [('重复单元续接', '选下一项'), ('重复单元纠错', '找出不合规则的一项')],
    '推理': [('可见线索排除', '指出依据'), ('补充缺少的信息', '提出一个问题')],
    '记忆': [('翻页后回忆物件', '说一说或指认'), ('翻页后重建顺序', '排一排')],
}


def present(value):
    return value is not None and value != '' and value != [] and value != {}


def resolve(raw, seed=None):
    if not isinstance(raw, dict):
        raise ValueError('配置必须是 JSON 对象')
    config = {}
    for key, value in raw.items():
        canonical = ALIASES.get(key, key)
        if canonical in config and config[canonical] != value:
            raise ValueError(f'中英字段冲突: {canonical}')
        config[canonical] = value
    config = {k: v for k, v in config.items() if present(v)}
    seed = seed if seed is not None else config.get('seed', secrets.randbits(63))
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError('seed 必须是整数')
    rng = random.Random(seed)
    age = config.get('age', [4, 6])
    age_range = age if isinstance(age, list) else [age, age]
    if (len(age_range) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                  or not 0 <= x < float('inf') for x in age_range)
            or age_range[0] > age_range[1]):
        raise ValueError('age 需为非负岁数或递增的两个岁数；自然语言请先规范化')
    for key, default in [('book_count', 1), ('page_count', DEFAULT_PAGE_COUNT)]:
        value = config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f'{key} 必须是正整数')
    if config.get('page_count', DEFAULT_PAGE_COUNT) < MIN_PAGE_COUNT:
        raise ValueError(f'page_count 常规最低{MIN_PAGE_COUNT}页，默认{DEFAULT_PAGE_COUNT}页；'
                         '角色设定图不计入书页。用户后续明确覆写时需人工编排并记录。')
    notes = ['配置是制作初稿；出图前需完成教学适配、角色DNA和题目可解性检查。',
             '正式绘本默认32页、常规最低30页；角色设定图不计入书页，不用空白或重复页凑数。',
             '按年龄与能力分章节、调整每次阅读量和单页负荷，不自动减少总页数。',
             'duplicate_configuration只比较整组配置，不证明训练结构不同；多本需复核规则与迁移任务。',
             'seed只复现本脚本的配置选择，不保证图像复现。']
    if 'age' not in config:
        notes.append('未提供读者年龄，采用4–6岁亲子共读假设。')
    if age_range[0] < 2:
        notes.append('不足2岁时改为成人陪伴的感知/互动图画活动，不套用解题训练。')
    unknown = sorted(set(config) - set(ALIASES.values()))
    if unknown:
        notes.append('以下额外参数原样保留，须由创作代理落实: ' + ', '.join(unknown))
    books = []
    seen = set()
    for index in range(config.get('book_count', 1)):
        for attempt in range(100):
            item = copy.deepcopy(config)
            item.pop('book_count', None)
            sources = {k: 'user' for k in item}

            def supply(key, value, source='random'):
                if key not in item:
                    item[key] = value
                    sources[key] = source

            supply('age', age, 'default')
            supply('difficulty', '标准', 'default')
            if 'character_refs' in item:
                supply('characters', {'source': 'provided_reference',
                                       'dna_status': 'pending_visual_inspection'}, 'reference')
            else:
                supply('characters', rng.choice(CHARACTERS))
            if 'scene' in item and 'theme' not in item:
                supply('theme', {'status': 'needs_contextual_design',
                                  'based_on_scene': item['scene']}, 'derived_pending')
            else:
                supply('theme', rng.choice(list(WORLDS)))
            if 'scene' not in item:
                if isinstance(item['theme'], str) and item['theme'] in WORLDS:
                    supply('scene', rng.choice(WORLDS[item['theme']]))
                else:
                    supply('scene', {'status': 'needs_contextual_design',
                                      'based_on_theme': item['theme']}, 'derived_pending')
            focus_options = ['观察', '分类', '数感', '空间'] if age_range[0] < 4 else list(METHODS)
            supply('learning_focus', rng.choice(focus_options))
            focus = item['learning_focus']
            options = METHODS.get(focus, [('按用户目标设计规则', '按能力选择反应方式')]) if isinstance(focus, str) else [('按用户目标设计规则', '按能力选择反应方式')]
            mechanism, response = rng.choice(options[:1] if age_range[0] < 4 else options)
            supply('style', '清楚轮廓、柔和色块、纸感绘本', 'default')
            supply('language', '简体中文', 'default')
            supply('page_count', DEFAULT_PAGE_COUNT, 'default')
            supply('format', '横向单页约3:2', 'default')
            signature = json.dumps([item['characters'], item['theme'], item['scene'], focus, mechanism], ensure_ascii=False, sort_keys=True)
            if signature not in seen:
                break
        duplicate = signature in seen
        seen.add(signature)
        item['seed'] = seed
        sources['seed'] = 'explicit' if seed == config.get('seed') else 'run_seed'
        books.append({'book_index': index + 1, 'parameters': item, 'parameter_sources': sources,
                      'design_proposal': {'mechanism': mechanism, 'response': response,
                                          'requires_age_and_constraint_review': True},
                      'duplicate_configuration': duplicate})
        if duplicate:
            notes.append(f'第{index + 1}本受固定参数限制出现重复组合，需人工改变规则或迁移任务，勿改用户参数。')
    return {'schema_version': 1, 'seed': seed, 'input_parameters': config, 'books': books, 'notes': notes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='可选JSON配置')
    parser.add_argument('--seed', type=int)
    parser.add_argument('--out', type=Path, help='新文件路径；不覆盖已有文件')
    args = parser.parse_args()
    try:
        raw = json.loads(args.input.read_text(encoding='utf-8')) if args.input else {}
        result = resolve(raw, args.seed)
        data = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(data)
            print(args.out.resolve())
        else:
            print(data, end='')
    except (ValueError, OSError) as exc:
        parser.exit(2, f'错误: {exc}\n')


if __name__ == '__main__':
    main()
