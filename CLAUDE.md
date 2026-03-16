# Briefcast

매일 아침 자동 팟캐스트 생성 서버. NotebookLM + Google Drive.

## 핵심 명령어
- 서버 시작: `cd C:/Git/briefcast && python server.py`
- 대시보드: http://localhost:8585
- NotebookLM 재인증: `notebooklm login`

## 기술 스택
- Python 3.12+, FastAPI, SQLite (aiosqlite)
- notebooklm-py (비공식, 쿠키 인증, 수 주마다 만료)
- feedparser + trafilatura + duckduckgo-search
- Google Drive API (OAuth)
- APScheduler (cron)

## 파이프라인
1. 스케줄러 (매일 06:00 KST) → `scheduler.run_all_topics()`
2. 주제별 뉴스 수집 → `collector.collect_topic()`
3. NotebookLM 오디오 생성 → `podcast.generate_podcast()`
4. Google Drive 업로드 → `drive.upload_file()`

## 주요 파일
| 파일 | 역할 |
|------|------|
| `server.py` | FastAPI 서버 + 대시보드 라우트 |
| `core/collector.py` | RSS + DuckDuckGo 뉴스 수집 + trafilatura 본문 추출 |
| `core/podcast.py` | NotebookLM API로 오디오 생성 |
| `core/drive.py` | Google Drive 업로드 |
| `core/database.py` | SQLite 스키마 + CRUD |
| `core/scheduler.py` | APScheduler + 파이프라인 오케스트레이션 |
| `templates/dashboard.html` | 대시보드 UI |

## 주의사항
- notebooklm-py: 비공식 API, Google 변경 시 깨질 수 있음
- credentials.json, token.json은 gitignored
- .env에 GOOGLE_DRIVE_FOLDER_ID 필수
