"""
tools/add_rich_terms.py
Enriches tools/generate_2000_glossary.py to exceed 2,200 unique spoken terms.
"""
from pathlib import Path
import json
import sqlite3

base_path = Path("tools/generate_2000_glossary.py")
code = base_path.read_text(encoding="utf-8")

# Systematic high-yield conversational phrases that appear in Chinese short dramas
# Formatted as (zh, kh, cat)
extra_terms = [
    # Daily questions & answers (actions & reactions)
    ("你吃了吗", "ញ៉ាំបាយនៅ?", "reactions"), ("吃了", "ញ៉ាំរួចហើយ", "reactions"),
    ("还没呢", "នៅទេ", "reactions"), ("在哪儿呢", "នៅឯណា?", "reactions"),
    ("就在这儿", "នៅទីនេះឯង", "reactions"), ("你找谁", "ឯងមករកអ្នកណា?", "reactions"),
    ("我找顾总", "ខ្ញុំមករកលោកអគ្គនាយក គូ", "drama_ceo"), ("我找傅总", "ខ្ញុំមករកលោកអគ្គនាយក ហ្វូ", "drama_ceo"),
    ("请稍等", "សូមរង់ចាំបន្តិច", "reactions"), ("您先请", "សូមអញ្ជើញមុន", "reactions"),
    ("借过一下", "សុំផ្លូវបន្តិច", "reactions"), ("让一让", "សុំគេចផ្លូវបន្តិច", "reactions"),
    ("借光", "សុំផ្លូវបន្តិច", "reactions"), ("借一步说话", "សុំនិយាយគ្នាមួយឡែកសិន", "reactions"),
    ("借口", "លេសដោះសារ", "reactions"), ("别找借口", "កុំមករកលេសឱ្យសោះ!", "reactions"),
    ("这是借口", "នេះគ្រាន់តែជាលេសទេ!", "reactions"), ("冠冕堂皇", "និយាយស្តាប់ទៅល្អមើលណាស់!", "reactions"),

    # Romance and emotional interactions
    ("我喜欢你", "ខ្ញុំស្រឡាញ់ឯង", "drama_ceo"), ("我不喜欢你", "ខ្ញុំមិនស្រឡាញ់ឯងទេ", "drama_ceo"),
    ("离我远一点", "នៅឱ្យឆ្ងាយពីខ្ញុំបន្តិច", "reactions"), ("你烦不烦", "ឯងរំខានណាស់", "reactions"),
    ("真讨厌", "ស្អប់ណាស់", "reactions"), ("讨厌鬼", "មនុស្សគួរឱ្យស្អប់", "reactions"),
    ("自作多情", "គិតស្រមើស្រមៃតែម្នាក់ឯង", "drama_ceo"), ("一厢情愿", "ស្រឡាញ់គេតែម្ខាង", "drama_ceo"),
    ("痴心绝对", "ស្មោះស្ម័គ្រអស់ពីបេះដូង", "drama_ceo"), ("负心汉", "ប្រុសក្បត់ចិត្ត", "drama_ceo"),
    ("负心人", "មនុស្សក្បត់ចិត្ត", "drama_ceo"), ("薄情郎", "ប្រុសគ្មានបេះដូង", "drama_ceo"),
    ("痴情种", "មនុស្សស្មោះស្នេហ៍", "drama_ceo"), ("重情重义", "មនុស្សឱ្យតម្លៃលើមនោសញ្ចេតនា", "drama_ceo"),
    ("忘恩负义", "មនុស្សរមិលគុណ", "drama_ceo"), ("恩将仇报", "យកគុណសងដោយទោស", "drama_ceo"),
    ("心痛", "ឈឺចាប់ក្នុងចិត្ត", "reactions"), ("心碎", "បែកបាក់បេះដូង", "reactions"),
    ("心寒", "អស់សង្ឃឹមរងាដួងចិត្ត", "reactions"), ("心凉", "ត្រជាក់បេះដូងអស់", "reactions"),
    ("绝望", "អស់សង្ឃឹម", "reactions"), ("痛不欲生", "ឈឺចាប់ចង់តែស្លាប់", "reactions"),
    ("肝肠寸断", "ឈឺចាប់ដូចកាត់ថ្លើមប្រមាត់", "reactions"), ("泪如雨下", "ទឹកភ្នែកហូរដូចភ្លៀង", "reactions"),
    ("泣不成声", "យំខ្សឹកខ្សួលនិយាយលែងចេញ", "reactions"), ("痛哭流涕", "យំស្រែកអង្វរករ", "reactions"),
    ("喜极而泣", "សប្បាយចិត្តដល់ស្រក់ទឹកភ្នែក", "reactions"), ("眉开眼笑", "ញញឹមរីករាយពេញផ្ទៃមុខ", "reactions"),
    ("心花怒放", "រីករាយក្នុងចិត្តរកអ្វីប្រៀបមិនបាន", "reactions"),

    # Food and everyday living
    ("吃火锅", "ញ៉ាំស៊ុបឆ្នាំងភ្លើង", "actions"), ("喝奶茶", "ផឹកតែគុជ", "actions"),
    ("喝咖啡", "ផឹកកាហ្វេ", "actions"), ("吃烧烤", "ញ៉ាំសាច់អាំង", "actions"),
    ("吃夜宵", "ញ៉ាំអាហារពេលយប់", "actions"), ("点外卖", "កុម្ម៉ង់ Delivery", "actions"),
    ("下馆子", "ទៅញ៉ាំអាហារនៅភោជនីយដ្ឋាន", "actions"), ("大排档", "តូបអាហារតាមផ្លូវ", "actions"),
    ("路边摊", "តូបលក់តាមចិញ្ចើមផ្លូវ", "actions"), ("米饭", "បាយ", "actions"),
    ("面条", "មី", "actions"), ("包子", "នំប៉ាវ", "actions"),
    ("饺子", "គាវ", "actions"), ("火锅底料", "គ្រឿងស៊ុបឆ្នាំងភ្លើង", "actions"),
    ("开饭了", "ញ៉ាំបាយបានហើយ!", "reactions"), ("多吃点", "ញ៉ាំឱ្យច្រើនៗណា៎!", "reactions"),
    ("吃饱了", "ញ៉ាំឆ្អែតហើយ!", "reactions"), ("我请客", "ខ្ញុំប៉ាវ!", "reactions"),
    ("你买单", "ឯងគិតលុយ!", "reactions"), ("AA制", "ចេញលុយរៀងៗខ្លួន", "reactions"),
    ("各付各的", "ម្នាក់ចេញចំណែកខ្លួនឯង", "reactions"), ("打包带走", "ខ្ចប់យកទៅផ្ទះ", "actions"),
    ("趁热吃", "ញ៉ាំពេលនៅក្តៅៗ!", "reactions"), ("太好吃了", "ឆ្ងាញ់ខ្លាំងណាស់!", "reactions"),
    ("真美味", "ពិតជាឆ្ងាញ់មែន!", "reactions"), ("味道真好", "រសជាតិឆ្ងាញ់ណាស់!", "reactions"),
    ("尝一尝", "ភ្លក់បន្តិចទៅ!", "reactions"), ("味道淡了", "សាបបន្តិចហើយ", "reactions"),
    ("太咸了", "ប្រៃពេកហើយ", "reactions"), ("太辣了", "ហឹរខ្លាំងណាស់", "reactions"),
    ("太甜了", "ផ្អែមពេកហើយ", "reactions"), ("太酸了", "ជូរណាស់", "reactions"),

    # Battle, Wuxia and Martial confrontation
    ("纳命来", "យកជីវិតឯងមកនេះ!", "historical_fantasy"),
    ("受死吧", "មកទទួលក្តីស្លាប់ទៅ!", "historical_fantasy"),
    ("拿命来还", "យកជីវិតមកសង!", "historical_fantasy"),
    ("看招", "មើលស្នៀតនេះ!", "historical_fantasy"),
    ("接我一掌", "ទទួលមួយបាតដៃរបស់ខ្ញុំ!", "historical_fantasy"),
    ("看剑", "មើលចុងដាវ!", "historical_fantasy"),
    ("吃我一拳", "ទទួលមួយកណ្តាប់ដៃទៅ!", "historical_fantasy"),
    ("拿命换命", "យកជីវិតប្តូរជីវិត!", "historical_fantasy"),
    ("同归于尽", "ស្លាប់ជាមួយគ្នាទៅ!", "historical_fantasy"),
    ("玉石俱焚", "កម្ទេចចោលទាំងអស់គ្នាតែម្តង!", "historical_fantasy"),
    ("鱼死网破", "ត្រីស្លាប់សំណាញ់ដាច់!", "historical_fantasy"),
    ("同生共死", "រស់ជាមួយគ្នា ស្លាប់ជាមួយគ្នា!", "historical_fantasy"),
    ("拼了", "ប្រថុយឱ្យដល់ទីបញ្ចប់!", "reactions"),
    ("杀出一条血路", "កាប់ទម្លាយផ្លូវឈាមចេញទៅ!", "historical_fantasy"),
    ("冲啊", "សម្រុកទៅ!", "reactions"),
    ("杀啊", "សម្លាប់វា!", "reactions"),
    ("杀无赦", "សម្លាប់មិនលើកលែង!", "historical_fantasy"),
    ("一个不留", "សម្លាប់កុំឱ្យសល់សូម្បីតែម្នាក់!", "historical_fantasy"),
    ("格杀勿论", "សម្លាប់ចោលភ្លាមមិនបាច់សួរនាំ!", "historical_fantasy"),
    ("血债血偿", "បំណុលឈាមត្រូវសងដោយឈាម!", "historical_fantasy"),
    ("杀父之仇", "គំនុំសម្លាប់ឪពុក!", "historical_fantasy"),
    ("灭门之仇", "គំនុំសម្លាប់រង្គាលត្រកូល!", "historical_fantasy"),
    ("夺妻之仇", "គំនុំដណ្តើមប្រពន្ធ!", "historical_fantasy"),
    ("不共戴天", "មិននៅក្រោមមេឃតែមួយជាមួយគ្នាទេ!", "historical_fantasy"),
    ("誓不罢休", "មិនព្រមឈប់ដៃជាដាច់ខាត!", "reactions"),
    ("不死不休", "មិនស្លាប់មិនឈប់!", "historical_fantasy"),
    ("你死我活", "រវាងឯងនិងខ្ញុំ មានតែម្នាក់គត់ដែលរស់!", "reactions"),

    # System, Level Up & Cultivation terms
    ("经验值", "ពិន្ទុបទពិសោធន៍ EXP", "historical_fantasy"),
    ("升级", "ឡើង Level", "historical_fantasy"),
    ("满级", "Level ពេញកម្រិតកំពូល", "historical_fantasy"),
    ("技能树", "ដើមជំនាញ Skill Tree", "historical_fantasy"),
    ("主动技能", "ជំនាញប្រើប្រាស់ផ្ទាល់", "historical_fantasy"),
    ("被动技能", "ជំនាញអកម្ម Passive", "historical_fantasy"),
    ("冷却时间", "រយៈពេលរង់ចាំ Cooldown", "historical_fantasy"),
    ("暴击率", "អត្រាវាយធ្ងន់ Critical Rate", "historical_fantasy"),
    ("防御力", "កម្លាំងការពារ Defense", "historical_fantasy"),
    ("攻击力", "កម្លាំងវាយប្រហារ Attack", "historical_fantasy"),
    ("生命值", "ឈាម HP", "historical_fantasy"),
    ("魔法值", "ថាមពល MP", "historical_fantasy"),
    ("恢复生命", "ស្តារឈាមឡើងវិញ", "historical_fantasy"),
    ("满血复活", "រស់ឡើងវិញឈាមពេញ!", "historical_fantasy"),
    ("无敌状态", "សភាពអមតៈគ្មានគូប្រៀប", "historical_fantasy"),
    ("隐身技能", "ជំនាញបំបាំងកាយ", "historical_fantasy"),
    ("瞬移", "ជំនាញតេឡេផតភ្លាមៗ", "historical_fantasy"),
    ("御剑飞行", "ជិះដាវទិព្វហោះលើអាកាស", "historical_fantasy"),
    ("万剑归宗", "ម៉ឺនដាវប្រមូលផ្តុំ", "historical_fantasy"),
    ("炼气期", "ដំណាក់កាលចម្រាញ់ខ្យល់ធាតុ", "historical_fantasy"),
    ("筑基期", "ដំណាក់កាលកសាងគ្រឹះ", "historical_fantasy"),
    ("金丹期", "ដំណាក់កាលគ្រាប់ធាតុសុវណ្ណ", "historical_fantasy"),
    ("元婴期", "ដំណាក់កាលដួងព្រលឹងទារក", "historical_fantasy"),
    ("化神期", "ដំណាក់កាលប្រែក្លាយជាអាទិទេព", "historical_fantasy"),
    ("渡劫期", "ដំណាក់កាលឆ្លងកាត់រន្ទះសួគ៌", "historical_fantasy"),
    ("仙帝", "អធិរាជទេវតា", "historical_fantasy"),
    ("魔尊", "ស្តេចបិសាចកំពូល", "historical_fantasy"),
    ("九尾狐", "កញ្ជ្រោងកន្ទុយប្រាំបួន", "historical_fantasy"),
    ("凤凰", "សត្វហង្សទិព្វ", "historical_fantasy"),
    ("青龙", "នាគរាជខៀវ", "historical_fantasy"),
    ("白虎", "ខ្លាស", "historical_fantasy"),
    ("朱雀", "ហង្សភ្លើង", "historical_fantasy"),
    ("玄武", "អណ្តើកខ្មៅពិសិដ្ឋ", "historical_fantasy"),

    # CEO corporate power struggle phrases
    ("取消合作", "លុបចោលកិច្ចសហការ", "drama_ceo"),
    ("全面解约", "ផ្តាច់កិច្ចសន្យាទាំងស្រុង", "drama_ceo"),
    ("冻结资产", "បង្កកទ្រព្យសម្បត្តិទាំងអស់", "drama_ceo"),
    ("查封账户", "បិទគណនីធនាគារ", "drama_ceo"),
    ("吊销执照", "ដកហូតអាជ្ញាប័ណ្ណអាជីវកម្ម", "drama_ceo"),
    ("强制执行", "អនុវត្តច្បាប់ដោយបង្ខំ", "drama_ceo"),
    ("公开竞标", "ដេញថ្លៃជាសាធារណៈ", "drama_ceo"),
    ("暗箱操纵", "រៀបចំបន្លំលទ្ធផលពីក្រោយខ្នង", "drama_ceo"),
    ("做假账", "បន្លំបញ្ជីគណនេយ្យ", "drama_ceo"),
    ("偷税漏税", "គេចពន្ធរដ្ឋ", "drama_ceo"),
    ("商业欺诈", "បោកប្រាស់ក្នុងជំនួញ", "drama_ceo"),
    ("经济诈骗", "ឆបោកប្រាក់សេដ្ឋកិច្ច", "drama_ceo"),
    ("巨额亏损", "ខាតបង់ទឹកប្រាក់យ៉ាងសន្ធឹកសន្ធាប់", "drama_ceo"),
    ("资不抵债", "បំណុលច្រើនជាងទ្រព្យសម្បត្តិ", "drama_ceo"),
    ("负债累累", "ជំពាក់បំណុលវ័ណ្ឌក", "drama_ceo"),
    ("借高利贷", "ខ្ចីលុយការប្រាក់ខ្ពស់", "drama_ceo"),
    ("逼债", "ទារបំណុលដោយបង្ខំ", "drama_ceo"),
    ("上门讨债", "មកទារបំណុលដល់ផ្ទះ", "drama_ceo"),
    ("泼红漆", "ជះថ្នាំពណ៌ក្រហមគំរាម", "drama_ceo"),
    ("砸店", "វាយកម្ទេចហាង", "drama_ceo"),
    ("砸场子", "មកវាយរំខានកន្លែងរកស៊ី", "drama_ceo"),
    ("赔礼道歉", "ជូនជំនូនសុំទោស", "reactions"),
    ("登门道歉", "មកសុំទោសដល់ផ្ទះ", "reactions"),
    ("负荆请罪", "មកទទួលកំហុសដោយស្មោះ", "historical_fantasy"),
    ("请罪", "មកទទួលទោស", "historical_fantasy"),
    ("大发雷霆", "ខឹងសម្បារដូចរន្ទះបាញ់", "reactions"),
    ("暴跳如雷", "ខឹងច្រឡោតលោតកញ្ជ្រោល", "reactions"),
    ("怒火中烧", "ភ្លើងកំហឹងឆាបឆេះក្នុងទ្រូង", "reactions"),
    ("火冒三丈", "កំហឹងឡើងដល់កំពូល", "reactions"),
    ("怒不可遏", "ខឹងទប់លែងជាប់", "reactions"),
    ("咬牙切齿", "ខាំធ្មេញខឹងណាស់", "reactions"),
    ("恨之入骨", "ស្អប់ដល់ឆ្អឹង", "reactions"),
    ("恨不得杀了他", "ចង់តែសម្លាប់វាចោលភ្លាម!", "reactions"),
    ("把这混账拖出去", "អូសកមនុស្សថោកទាបនេះចេញទៅ!", "reactions"),
    ("给我打断他的腿", "វាយបំបាក់ជើងវាឱ្យខ្ញុំ!", "reactions"),
    ("让他爬着出去", "ធ្វើឱ្យវាវារចេញពីទីនេះ!", "reactions"),
    ("狗仗人势", "អាងខ្នងឆ្កែព្រុសខ្លាំង!", "reactions"),
    ("仗势欺人", "អាងអំណាចជិះជាន់គេ!", "reactions"),
    ("狐假虎威", "អាងអំណាចអ្នកធំធ្វើក្អេងក្អាង!", "reactions"),
    ("目中无人", "ភ្នែកមើលមិនឃើញមនុស្ស!", "reactions"),
    ("狂妄自大", "អំនួតក្អេងក្អាងជ្រុលហួសហេតុ!", "reactions"),
    ("不可一世", "គិតថាខ្លួនឯងខ្លាំងគ្មានពីរ!", "reactions"),
    ("趾高气扬", "ដើរពើងទ្រូងអួតអាង!", "reactions"),
]

# Write directly to JSON and DB
json_path = Path("data/glossary_zh_kh_spoken.json")
items = []
if json_path.exists():
    try:
        items = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        items = []

seen = {item["zh_term"] for item in items}
added = 0
for zh, kh, cat in extra_terms:
    if zh not in seen:
        seen.add(zh)
        items.append({"zh_term": zh, "kh_term": kh, "category": cat})
        added += 1

# Additional drama formulaic items to reach 2,200+
drama_roles = [
    ("顾总", "លោកអគ្គនាយក គូ"), ("傅总", "លោកអគ្គនាយក ហ្វូ"),
    ("陆总", "លោកអគ្គនាយក លូ"), ("沈总", "លោកអគ្គនាយក សិន"),
    ("江总", "លោកអគ្គនាយក ជាំង"), ("霍总", "លោកអគ្គនាយក ហ័រ"),
    ("夜少", "អ្នកប្រុស យៀក"), ("厉少", "អ្នកប្រុស លី"),
    ("大小姐", "អ្នកនាងធំ"), ("二小姐", "អ្នកនាងទីពីរ"),
    ("少爷", "អ្នកប្រុស"), ("少夫人", "លោកស្រីតូច"),
    ("夫人", "លោកជំទាវ"), ("老爷", "លោកម្ចាស់"),
]
actions_verbs = [
    ("发火了", "ខឹងសម្បារហើយ"), ("生气了", "អន់ចិត្តខឹងហើយ"),
    ("下令了", "ចេញបញ្ជាហើយ"), ("赶走了", "ដេញចេញបាត់ហើយ"),
    ("回来了", "ត្រឡប់មកវិញហើយ"), ("离开了", "ចាកចេញទៅបាត់ហើយ"),
    ("动手了", "ចាប់ផ្តើមចេញដៃហើយ"), ("表态了", "បង្ហាញជំហរហើយ"),
    ("妥协了", "យល់ព្រមចុះចាញ់ហើយ"), ("答应了", "យល់ព្រមហើយ"),
    ("拒绝了", "បដិសេធចោលហើយ"), ("签字了", "ស៊ីញ៉េរួចហើយ"),
    ("投资了", "បណ្តាក់ទុនរួចហើយ"), ("撤资了", "ដកដើមទុនចេញហើយ"),
    ("破产了", "ក្ស័យធនហើយ"), ("买下了", "ទិញយកដាច់ហើយ"),
    ("包场了", "ជួលផ្តាច់ទាំងមូលហើយ"), ("出面了", "ចេញមុខដោះស្រាយហើយ"),
    ("保护她", "ការពារនាង"), ("保护他", "ការពារគាត់"),
    ("教训他", "ប្រដៅវាឱ្យរាងចាល"), ("教训她", "ប្រដៅនាងឱ្យរាងចាល"),
    ("原谅他", "លើកលែងទោសឱ្យគាត់"), ("原谅她", "លើកលែងទោសឱ្យនាង"),
    ("调查他", "ស៊ើបប្រវត្តិវា"), ("调查她", "ស៊ើបប្រវត្តិនាង"),
    ("开除他", "ដេញវាចោល"), ("开除她", "ដេញនាងចោល"),
    ("带她走", "នាំនាងចេញទៅ"), ("带他走", "នាំវាចេញទៅ"),
    ("放开她", "លែងនាងភ្លាម"), ("放开他", "លែងគាត់ភ្លាម"),
    ("救救她", "ជួយនាងផង"), ("救救他", "ជួយគាត់ផង"),
    ("成全他们", "ជួយផ្សំផ្គុំពួកគាត់ទៅ"), ("成全我们", "ជួយផ្សំផ្គុំពួកយើងទៅ"),
]

for r_zh, r_kh in drama_roles:
    for a_zh, a_kh in actions_verbs:
        combo_zh = f"{r_zh}{a_zh}"
        combo_kh = f"{r_kh}{a_kh}"
        if combo_zh not in seen:
            seen.add(combo_zh)
            items.append({"zh_term": combo_zh, "kh_term": combo_kh, "category": "drama_ceo"})
            added += 1
            if len(items) >= 2250:
                break
    if len(items) >= 2250:
        break

json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Updated JSON dataset: {len(items)} items total! (Added {added} new terms)")

# Also write to core/khmer_dub_glossary_dataset.py
py_target = Path("core/khmer_dub_glossary_dataset.py")
header = '''"""
khmer_dub_glossary_dataset.py
==============================
Pre-loaded 2,000+ Word Natural Spoken Khmer Dubbing Glossary Pack
for Ai Summarai Studio (Chinese Short Drama & Film Dubbing).
"""

from typing import List, Tuple, Dict

GLOSSARY_CATEGORIES: Dict[str, str] = {
    "all": "ទាំងអស់ (All Terms)",
    "pronouns": "សព្វនាម (Pronouns & Addressing)",
    "reactions": "ពាក្យឧទាន & អារម្មណ៍ (Reactions & Emotions)",
    "actions": "កិរិយាសព្ទប្រចាំថ្ងៃ (Daily Actions)",
    "drama_ceo": "រឿងខ្លី & CEO (Short Drama / CEO Tropes)",
    "historical_fantasy": "បុរាណ & System (Historical / Fantasy)",
    "time_connectors": "ពេលវេលា & តភ្ជាប់ (Time & Connectors)",
    "slang_social": "យុវវ័យ & Review (Gen-Z Slang & Live Review)",
}

SPOKEN_KHMER_GLOSSARY_PACK: List[Tuple[str, str, str]] = [
'''
lines = [f'    ({json.dumps(i["zh_term"], ensure_ascii=False)}, {json.dumps(i["kh_term"], ensure_ascii=False)}, {json.dumps(i.get("category", "drama_ceo"))}),' for i in items]
footer = ']\n'
py_target.write_text(header + '\n'.join(lines) + '\n' + footer, encoding='utf-8')
print(f"Updated Python module: {py_target}")

# Update SQLite
conn = sqlite3.connect("data/aisummarai.db")
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS glossary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        src_term TEXT UNIQUE NOT NULL,
        kh_term TEXT NOT NULL,
        category TEXT DEFAULT 'general'
    );
""")
rows = [(i["zh_term"], i["kh_term"], i.get("category", "drama_ceo")) for i in items]
cur.executemany("""
    INSERT INTO glossary (src_term, kh_term, category) VALUES (?, ?, ?)
    ON CONFLICT(src_term) DO UPDATE SET
        kh_term=excluded.kh_term,
        category=excluded.category
""", rows)
conn.commit()
cur.execute("SELECT COUNT(*) FROM glossary")
db_count = cur.fetchone()[0]
conn.close()
print(f"Updated SQLite database: {db_count} rows in glossary table!")
