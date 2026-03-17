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
- feedparser + trafilatura + duckduckgo-search + googlenewsdecoder
- Google Drive API (OAuth, Desktop app 타입)
- APScheduler (cron, Asia/Seoul)
- Playwright Chromium (notebooklm-py 의존)

## 아키텍처: 채널 기반
- **채널**: 독립 스케줄 + 주제 조합 + 오디오 설정 → 채널마다 팟캐스트 1개 생성
- 채널 여러 개 = 하루에 여러 팟캐스트 (예: 07:00 뉴스, 12:00 경제 브리핑)
- **주제**: 미리 정의된 토글 버튼 (26종, `TOPIC_SEARCH_KEYWORDS`) + 커스텀 키워드
- 각 주제는 ko + en 자동 검색 (Languages 설정 불필요)

## 파이프라인
1. 스케줄러 (채널별 설정 시간) → `scheduler.run_channel()`
2. 선택된 주제별 ko/en 개별 뉴스 수집 → `collector.collect_channel_topics()`
   - Google News RSS (when:24h, googlenewsdecoder로 실제 URL 변환)
   - DuckDuckGo 뉴스 — 순차 실행 (rate limit 방지)
   - 중복 제거 후 최대 10건으로 제한 (본문 길이 순)
3. NotebookLM 한국어 오디오 생성 (유쾌한 톤) → `podcast.generate_podcast()`
4. Google Drive 업로드 (날짜별 하위 폴더) → `drive.upload_file()`

## 주요 파일
| 파일 | 역할 |
|------|------|
| `server.py` | FastAPI 서버 + 대시보드 + Channels/Episodes API |
| `core/collector.py` | TOPIC_SEARCH_KEYWORDS(26종) + 다중 소스 뉴스 수집 + trafilatura 본문 추출 |
| `core/podcast.py` | NotebookLM API (AudioFormat/AudioLength enum, language='ko', instructions) |
| `core/drive.py` | Google Drive OAuth + 업로드 + 폴더 생성 |
| `core/database.py` | SQLite 스키마 (channels, episodes) + CRUD |
| `core/scheduler.py` | APScheduler + 채널별 파이프라인 + reschedule_all |
| `templates/dashboard.html` | 대시보드 UI (채널 관리 + 주제 토글 + 에피소드 히스토리) |

## DB 스키마
- `channels`: id, name, schedule_hour/minute, topics(JSON), custom_topics(JSON), audio_format, audio_length, enabled
- `episodes`: id, channel_id(FK), date, status, articles_count, mp3_path, drive_id, error, timestamps

## notebooklm-py API 주의사항
- `sources.add_text(notebook_id, title, content)` — title이 두 번째, content가 세 번째
- `artifacts.generate_audio()` — AudioFormat/AudioLength enum 필수 (문자열 불가), `instructions` 파라미터로 톤 설정 가능
- `artifacts.wait_for_completion(notebook_id, task_id)` — poll 대신 사용, timeout 충분히 (900초+)
- `artifacts.download_audio(notebook_id, output_path)` — 파일 경로에 직접 저장 (bytes 반환 아님)
- `notebooks.list()` → Notebook 객체의 이름은 `.title` (`.name` 아님)
- status 값: `in_progress` → `completed` (대문자 아님)
- 소스 15개 이상이면 오디오 생성이 매우 느려짐 → 10건 이하 권장
- Google News RSS URL은 `googlenewsdecoder.new_decoderv1()`로 실제 URL 변환 필요

## 인프라
- Server Manager(`localhost:9000`)에 `briefcast` ID로 등록됨
- venv 경로: `C:/Git/briefcast/venv/Scripts/python.exe`
- Google Cloud 프로젝트: `briefcast-490412`
- Drive 폴더 ID: `.env`의 `GOOGLE_DRIVE_FOLDER_ID` 참조
