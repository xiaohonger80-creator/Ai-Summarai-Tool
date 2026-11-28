# 🎬 Ai Summarai v1.7.8 — មគ្គុទ្ទេសក៍ប្រើប្រាស់ពេញលេញ (Complete User Guide KH / EN)
**All-in-One AI Video, Dubbing, Story Recap & VideoFX Studio (Low-Spec & High-Spec PC Ready)**

---

## 🚀 ១. របៀបបើក និងជ្រើសរើសផ្ទាំងធ្វើការ (How to Launch & Choose Your Workspace)

អ្នកអាចបើកកម្មវិធីតាមរយៈ Shortcut **Ai Summarai** លើ Desktop ឬវាយក្នុង Terminal៖
```powershell
python main.py
```

កម្មវិធីមាន **៣ ផ្ទាំងស្ទូឌីយោ** ដែលធ្វើការរួមគ្នា៖
1. **ផ្ទាំងមេ (Main Dubbing & Timeline Studio):** សម្រាប់កាត់តលើ Timeline, ប្រើ **1-Click Auto Dub & Export**, កែតារាង Subtitle, ដាក់ភ្លេង/SFX, និងប្រើប៊ូតុង **Fill Gaps (បំពេញចន្លោះ)**។
2. **ផ្ទាំង 🚀 All-in-One AI Studio (4-Zone Workspace):** ចុចម៉ឺនុយ **`🛠️ Tools ▾` -> `🚀 All-in-One AI Studio (Recap, Dub & FX)`** ដើម្បីបើកផ្ទាំងរួមបញ្ចូលគ្នាទាំង ៤ តំបន់ (Preview Canvas, តារាង Voice FX, Batch Queue Auto-Splitter, និង 3-Tab Inspector)។
3. **ផ្ទាំង 🎬 VideoFX Studio:** ចុច **`🛠️ Tools ▾` -> `🎬 VideoFX Studio (3D LUTs, Masking & Text)`** សម្រាប់លាយពណ៌ភាពយន្ត 3D `.cube` LUTs, ម៉ាស់បិទបាំងអក្សរចិន និងអក្សររត់ `.ASS`។

---

## 💻 ២. របៀបកំណត់ឲ្យដើរស្រាលបំផុតលើម៉ាស៊ីនខ្សោយ (Low-Spec PC Smooth Mode — CPU < 40%)

ប្រសិនបើកុំព្យូទ័ររបស់អ្នកមាន RAM 8GB ឬគ្មានកាតក្រាហ្វិកធំ (ឬចង់ទុក CPU ធ្វើការងារផ្សេងទៀត)៖
1. **បើក Low-Spec PC Profile:**
   - នៅក្នុងផ្ទាំង **All-in-One AI Studio** ត្រង់របារខាងលើ សូមជ្រើសរើស **`Low-Spec PC (4GB VRAM Safe)`**។
   - ប្រព័ន្ធនឹងកំណត់ Thread Cap ត្រឹម `2 Threads` ដោយស្វ័យប្រវត្តិ, បញ្ចុះល្បឿនចាប់ Frame OCR មក `0.5 FPS` (រំលង Frame ដដែលៗ 70%), បង្រួម Batch Size ត្រឹម `4`, និងសម្អាត RAM/VRAM (`unload()`) ភ្លាមៗក្រោយចប់ជំហាននីមួយៗ!
2. **ពិនិត្យប្រព័ន្ធជាមុន (Setup & Models Manager):**
   - ចុចប៊ូតុង **`🟢 Setup & Models`** នៅលើ Toolbar (ឬក្នុង `Tools ▾ -> ពិនិត្យប្រព័ន្ធ & ម៉ូដែល AI`)។
   - វានឹងបង្ហាញស្ថានភាព **GPU Encoder** (`NVENC` / `AMD AMF` / `Intel QSV` / `CPU x264`), **FFmpeg**, និង **Ollama Local AI**។

---

## 🎯 ៣. របៀបលេង និងប្រើប្រាស់មុខងារសំខាន់ៗទាំង ៧ (Step-by-Step Gameplay Guide)

### ជំហានទី ១៖ បើកវីដេអូ ឬដាក់រឿងភាគច្រើនចូល Batch Queue (Open Video & Auto-Split Episodes)
* **វីដេអូទោល៖** ចុច **`📂 Open Video (Ctrl+O)`** ឬទាញវីដេអូ (`MP4, MKV, MOV, AVI`) ទម្លាក់ចូលក្នុងកម្មវិធី។
* **រឿងភាគវែងៗ (Auto-Split Episodes):**
  1. នៅផ្នែកខាងក្រោមនៃផ្ទាំង All-in-One Studio ត្រង់តារាង **Batch Queue** សូមជ្រើសរើស **`Auto-Split Episodes: Every 10 Min`** (ឬ `15 Min` / `20 Min`)។
  2. ចុច **`+ Add Files`** ឬ **`+ Add Folder`**។
  3. កម្មវិធីនឹងកាត់វីដេអូរឿងវែង (ឧទាហរណ៍ ១ ម៉ោង) ជាភាគខ្លីៗ ១៥ នាទី ក្នុងរយៈពេលតែ ២-៣ វិនាទីប៉ុណ្ណោះ រួចដាក់តម្រៀបក្នុង Queue ដើម្បីបកប្រែ និងបញ្ចូលសំឡេងបន្តបន្ទាប់គ្នាដោយស្វ័យប្រវត្តិ!

### ជំហានទី ២៖ ស្កេនយកអក្សរចិន ឬស្តាប់សំឡេង (Extract Subtitles & Fill Gaps)
* នៅក្នុង **Tab 1 (`1. Extract & Translate`)** អ្នកអាចជ្រើសរើសម៉ាស៊ីនស្កេន ៤ ប្រភេទ៖
  1. **`Hard-Subtitle OCR (PaddleOCR)`**: សម្រាប់វីដេអូដែលមានអក្សរចិនជាប់លើវីដេអូស្រាប់។
  2. **`Audio ASR (FunASR SenseVoice)`** ឬ **`WhisperX (int8 CPU)`**: សម្រាប់ស្តាប់សំឡេងនិយាយក្នុងវីដេអូដែលគ្មានអក្សរ។
  3. **`Hybrid (OCR Primary + ASR Check)`**: អានអក្សរលើវីដេអូផង និងស្តាប់សំឡេងបំពេញចន្លោះដែលខ្វះផង!
* **មុខងារ `🔍 Fill Gaps (បំពេញចន្លោះ)` លើ Timeline:**
  - ប្រសិនបើស្កេន OCR រួច ឃើញមានចន្លោះណាដែលតួអង្គនិយាយតែគ្មានអក្សរចិនលើអេក្រង់ សូមចុចប៊ូតុង **`🔍 Fill Gaps (បំពេញចន្លោះ)`** លើរបារ Timeline។ កម្មវិធីនឹងកាត់យកតែចន្លោះនោះទៅស្តាប់សំឡេង បកប្រែជាខ្មែរ និងបង្កើតសំឡេងខ្មែរដាក់បំពេញឲ្យភ្លាមៗ!

### ជំហានទី ៣៖ បកប្រែជាភាសាខ្មែរ ឬសរសេរសម្រាយរឿង (Translate & AI Story Recap)
* **ជម្រើស AI Provider ៣ របៀប (តាមចិត្តជ្រើសរើស)៖**
  1. **🌐 Free Google Translate (`google-free`)**: ឥតគិតថ្លៃ ១០០% មិនបាច់មាន API Key និងមិនស៊ីកម្លាំង CPU/GPU។
  2. **🦙 100% Local Offline (`Ollama`)**: ប្រើម៉ូដែលក្នុងម៉ាស៊ីនផ្ទាល់ (ណែនាំ `qwen2.5:7b` ឬ `qwen2.5:3b` សម្រាប់ម៉ាស៊ីនខ្សោយ) មិនបាច់មានអ៊ីនធឺណិត។
  3. **⚡ Cloud API (`Gemini 2.5 Flash` / `OpenAI`)**: គាំទ្រ **Multi-API Key Pool** (ដាក់ Key ច្រើនបន្ទាត់ដើម្បីប្តូរ Key ស្វ័យប្រវត្តិពេលជាប់ Limit 429)។
* **ជម្រើសបកប្រែ៖**
  - **`Story Context Mode`**: អានសាច់រឿងទាំងមូលបង្កើតវចនានុក្រមឈ្មោះតួអង្គ និងសព្វនាម (បង, អូន, ទូលបង្គំ, លោកគ្រូ) មុននឹងបកប្រែ។
  - **`AI Story Recap`** (ក្នុង Tab 2): បម្លែងការសន្ទនាក្នុងរឿងទៅជាអត្ថបទនិទានរឿង/សម្រាយរឿង (បុរសទី ៣) ដ៏ជក់ចិត្ត!

### ជំហានទី ៤៖ កំណត់សំឡេងតួអង្គ, ក្លូនសំឡេង & បែបផែនសំឡេងពិសេស (Multi-Speaker & Voice FX)
1. **បែងចែកសំឡេងតួអង្គ (`🎙️ Speaker Voices...`):**
   - ចុចប៊ូតុង **`🎙️ Speaker Voices...`** ក្នុង Tab 2 (ឬ Right-Click លើតារាង -> `Map Speaker Roles`)។
   - កំណត់សំឡេងប្រុស (`Piseth`), ស្រី (`Sreymom`), ឬសំឡេងក្លូន (`Voice Clone`) សម្រាប់ `SPEAKER_00`, `SPEAKER_01`, និង `NARRATOR` រួចចុច **`▶ Test Voice`** ដើម្បីស្តាប់សាកល្បង។
2. **ដាក់បែបផែនសំឡេងពិសេស (`Voice FX` Column ក្នុងតារាង):**
   - នៅលើបន្ទាត់នីមួយៗក្នុងតារាង អ្នកអាចប្តូរប្រអប់ **`Voice FX`**៖
     * 🔊 **`Normal`**: សំឡេងនិយាយធម្មតា ច្បាស់ល្អ។
     * 💭 **`Inner Thought`**: សំឡេងគិតក្នុងចិត្ត (មានអេកូ Reverb រំពងស្រទន់)។
     * 📞 **`Phone Call`**: សំឡេងនិយាយតាមទូរស័ព្ទពិតៗ។
     * 📻 **`Radio`**: សំឡេងនិយាយតាមវិទ្យុទាក់ទង ឬឧឃ្ឃោសនស័ព្ទ។
3. **Somleng Khmer Smart Reader:**
   - រាល់លេខ (`125`), លុយ (`$100`, `50000៛`, `¥20`), និងភាគរយ (`50%`) ក្នុងអត្ថបទខ្មែរ នឹងត្រូវបម្លែងជាពាក្យនិយាយខ្មែរពេញលេញដោយស្វ័យប្រវត្តិមុនពេលអាន!

### ជំហានទី ៥៖ លាយពណ៌ 3D LUTs, បិទបាំងអក្សរចិន & អក្សររត់ (Tab 3: Text FX, Mask & LUTs)
* **បិទបាំងអក្សរចិនដើម:** ធីក **`Bottom Hardsub Cover Box`** ឬបើក **`Enable Video Masking`** ដើម្បីធ្វើឲ្យព្រាល (Blur) ឬដាក់ប្រអប់បាំងអក្សរចិនខាងក្រោម។
* **អក្សរខ្មែររត់ និងចលនា (`Animated Text`):** ជ្រើសរើស `Static Styled Subtitles`, `Horizontal Scrolling Marquee` (អក្សររត់ដេក), `Vertical Credits Roll` (អក្សររត់ឡើងលើ), ឬ `Kinetic Pop-In` (អក្សរលោត)។
* **ពណ៌ភាពយន្ត (`3D Color LUT Grading`):** ធីក **`Enable 3D LUT Grading`** រួចជ្រើសរើសពណ៌ភាពយន្ត (ដូចជា `Cinematic_Teal_Orange.cube`, `Kodak_Vintage_Film.cube`, `Vivid_Social_Pop.cube`) និងទាញ Slider **`Intensity (0-100%)`**។
* **មើលលទ្ធផលភ្លាមៗមិនបាច់រង់ចាំយូរ:** ចុចប៊ូតុងពណ៌បៃតង **`🖼️ Render Preview Frame`** (ប្រើពេលតែ **0.14 វិនាទី** ប៉ុណ្ណោះដើម្បីបង្ហាញរូបភាពវីដេអូដែលមានទាំងពណ៌ LUT + ម៉ាស់ + អក្សរខ្មែរ)!

### ជំហានទី ៦៖ រក្សាទុកគម្រោង `.vfxproj` & Smart TTS Cache (កែអក្សរហើយ Export វិញលឿនដូចផ្លេកបន្ទោរ)
1. ចុច **`💾 Save Project (Ctrl+S)`** ដើម្បីរក្សាទុកការងារទាំងអស់ជាឯកសារ `.vfxproj` (ថ្ងៃក្រោយអាចចុច **`📁 Load Project`** មកធ្វើបន្តទៀតបានគ្រប់ពេល)។
2. **ល្បឿន Smart TTS Cache:** ក្រោយពេលអ្នកផលិតវីដេអូចប់ម្តង ប្រសិនបើអ្នកចង់កែអក្សរខ្មែរ ២-៣ បន្ទាត់ឲ្យពិរោះជាងមុន គ្រាន់តែកែក្នុងតារាង រួចចុច **`🚀 Start Pipeline (F5)`** ម្តងទៀត — បន្ទាត់ទាំងអស់ដែលមិនបានកែ នឹងត្រូវទាញចេញពី **SHA-256 Smart Cache** ភ្លាមៗ (`0.00s`) ដោយបង្កើតសំឡេងថ្មីតែ ២-៣ បន្ទាត់ដែលអ្នកបានកែប៉ុណ្ណោះ!

---

## ⌨️ ៤. បញ្ជីផ្លូវកាត់លើក្តារចុច (Keyboard Shortcuts Cheat Sheet)

| គ្រាប់ចុច (Shortcut) | មុខងារ (Action) |
| :--- | :--- |
| **`Ctrl + O`** | បើកឯកសារវីដេអូថ្មី (`Open Video`) |
| **`Ctrl + S`** | រក្សាទុកគម្រោងជា `.vfxproj` (`Save Project`) |
| **`F5`** | ចាប់ផ្តើមដំណើរការផលិតវីដេអូទាំង ៤ ដំណាក់កាល (`Start Pipeline`) |
| **`Esc`** | បោះបង់ ឬផ្អាកដំណើរការភ្លាមៗ (`Cancel Pipeline`) |
| **`Space`** | ចាក់ ឬផ្អាកវីដេអូក្នុងផ្ទាំងមេ (`Play / Pause`) |
| **`Right-Click លើតារាង`** | បើកម៉ឺនុយកំណត់សំឡេងតួអង្គ និងប្តូរ `Voice FX` (`Inner Thought` / `Phone Call`) |
