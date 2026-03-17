# Briefcast

매일 아침 한국어 자동 팟캐스트 생성 서버. NotebookLM + Google Drive.

## 핵심 명령어
- 서버 시작: Server Manager에서 자동 시작 또는 `cd C:/Git/briefcast && venv/Scripts/python.exe server.py`
- 대시보드: http://localhost:8585
- NotebookLM 재인증: `cd C:/Git/briefcast && venv\Scripts\activate && notebooklm login`
- Drive 재인증: `venv\Scripts\python.exe -c "from core.drive import _get_credentials; _get_credentials()"`

## 기술 스택
- Python 3.13, FastAPI, SQLite (aiosqlite)
- notebooklm-py 0.3.4 (비공식, 쿠키 인증, 수 주마다 만료)
- feedparser + trafilatura + duckduckgo-search
- Google Drive API (OAuth, Desktop app 타입)
- APScheduler (cron, Asia/Seoul)
- Playwright Chromium (notebooklm-py 의존)

## 파이프라인
1. 스케줄러 (대시보드 설정 시간, 기본 06:00 KST) → `scheduler.run_all_topics()`
2. 주제별 뉴스 수집 (최근 24h) → `collector.collect_topic()`
   - Google News RSS (when:24h), DuckDuckGo 뉴스, YouTube, X(Twitter)
3. NotebookLM 한국어 오디오 생성 → `podcast.generate_podcast()`
4. Google Drive 업로드 (날짜별 하위 폴더) → `drive.upload_file()`

## 주요 파일
| 파일 | 역할 |
|------|------|
| `server.py` | FastAPI 서버 + 대시보드 + Settings/Topics/Episodes API |
| `core/collector.py` | 다중 소스 뉴스 수집 (RSS + YouTube + X + DuckDuckGo) + trafilatura 본문 추출 |
| `core/podcast.py` | NotebookLM API (AudioFormat/AudioLength enum, language='ko', wait_for_completion) |
| `core/drive.py` | Google Drive OAuth + 업로드 + 폴더 생성 |
| `core/database.py` | SQLite 스키마 (topics, episodes, settings) + CRUD |
| `core/scheduler.py` | APScheduler + 파이프라인 + reschedule 지원 |
| `templates/dashboard.html` | 대시보드 UI (주제 관리 + Settings 패널 + 에피소드 히스토리) |

## notebooklm-py API 주의사항
- `sources.add_text(notebook_id, title, content)` — title이 두 번째, content가 세 번째
- `artifacts.generate_audio()` — AudioFormat/AudioLength enum 필수 (문자열 불가)
- `artifacts.wait_for_completion(notebook_id, task_id)` — poll 대신 사용
- `artifacts.download_audio(notebook_id, output_path)` — 파일 경로에 직접 저장 (bytes 반환 아님)
- `notebooks.list()` → Notebook 객체의 이름은 `.title` (`.name` 아님)
- status 값: `in_progress` → `completed` (대문자 아님)

## 인프라
- Server Manager(`localhost:9000`)에 `briefcast` ID로 등록됨
- venv 경로: `C:/Git/briefcast/venv/Scripts/python.exe`
- Google Cloud 프로젝트: `briefcast-490412`
- Drive 폴더 ID: `.env`의 `GOOGLE_DRIVE_FOLDER_ID` 참조
