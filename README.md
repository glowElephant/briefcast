# Briefcast

매일 아침, 원하는 주제로 AI 팟캐스트를 자동 생성하는 서버.

Google News + DuckDuckGo에서 뉴스를 수집하고, NotebookLM으로 팟캐스트 오디오를 생성하여 Google Drive에 저장한다.

## 기능

- 웹 대시보드에서 주제 관리 (추가/수정/삭제/토글)
- 주제별 뉴스 자동 수집 (Google News RSS + DuckDuckGo + trafilatura 본문 추출)
- NotebookLM Audio Overview로 팟캐스트 MP3 생성
- Google Drive 자동 업로드
- 스케줄러 (매일 지정 시간 자동 실행)
- 수동 즉시 실행 (대시보드에서 Run 버튼)

## 기술 스택

| 구성 | 기술 |
|------|------|
| 웹 서버 | FastAPI + Jinja2 |
| 뉴스 수집 | feedparser, trafilatura, duckduckgo-search |
| 팟캐스트 | notebooklm-py (비공식) |
| 저장소 | Google Drive API |
| DB | SQLite (aiosqlite) |
| 스케줄러 | APScheduler |

## 사전 준비

### 1. NotebookLM 인증

notebooklm-py는 비공식 라이브러리로, 브라우저 쿠키 기반 인증을 사용한다.

```bash
# Playwright 설치
pip install "notebooklm-py[browser]"
playwright install chromium

# 로그인 (브라우저 창이 열림 → Google 계정 로그인)
notebooklm login
```

- 쿠키는 `~/.notebooklm/storage_state.json`에 저장됨
- **수 주마다 만료** — 만료 시 `notebooklm login` 재실행 필요

### 2. Google Drive OAuth

Google Drive에 파일을 업로드하려면 OAuth 자격증명이 필요하다.

1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. 프로젝트 생성 (또는 기존 프로젝트 사용)
3. **APIs & Services > Library** → "Google Drive API" 검색 → 활성화
4. **APIs & Services > Credentials** → **Create Credentials > OAuth client ID**
   - Application type: **Desktop app**
   - 이름: `briefcast` (아무거나)
5. 생성된 클라이언트의 **JSON 다운로드** → 프로젝트 루트에 `credentials.json`으로 저장
6. **OAuth consent screen** 설정:
   - User type: External
   - 앱 이름, 이메일 입력
   - Scopes: `https://www.googleapis.com/auth/drive.file`
   - Test users: 본인 Gmail 추가

첫 실행 시 브라우저가 열리며 권한 승인 → `token.json` 자동 생성.

### 3. Google Drive 폴더 준비

1. Google Drive에서 팟캐스트 저장용 폴더 생성 (예: `Briefcast`)
2. 폴더 URL에서 ID 복사: `https://drive.google.com/drive/folders/{FOLDER_ID}`
3. `.env`에 `GOOGLE_DRIVE_FOLDER_ID={FOLDER_ID}` 설정

## 설치

```bash
cd C:/Git/briefcast

# 가상환경 (권장)
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일 편집하여 GOOGLE_DRIVE_FOLDER_ID 등 설정
```

## 실행

```bash
python server.py
```

대시보드: http://localhost:8585

## 설정 (.env)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 서버 바인드 주소 |
| `PORT` | `8585` | 서버 포트 |
| `GOOGLE_DRIVE_FOLDER_ID` | (필수) | Drive 업로드 대상 폴더 ID |
| `SCHEDULE_HOUR` | `6` | 실행 시각 (시) |
| `SCHEDULE_MINUTE` | `0` | 실행 시각 (분) |
| `AUDIO_FORMAT` | `DEEP_DIVE` | NotebookLM 포맷 (DEEP_DIVE/BRIEF/CRITIQUE/DEBATE) |
| `AUDIO_LENGTH` | `DEFAULT` | 오디오 길이 (SHORT/DEFAULT/LONG) |
| `MAX_ARTICLES_PER_TOPIC` | `10` | 주제당 최대 수집 기사 수 |
| `ARTICLE_FETCH_DELAY` | `1.5` | 기사 수집 간 딜레이 (초) |

## 구조

```
briefcast/
├── server.py              ← FastAPI 서버 + 대시보드
├── core/
│   ├── collector.py       ← 뉴스 수집 (RSS + 검색 + 본문 추출)
│   ├── podcast.py         ← NotebookLM 오디오 생성
│   ├── drive.py           ← Google Drive 업로드
│   ├── database.py        ← SQLite DB
│   └── scheduler.py       ← 스케줄러 + 파이프라인
├── templates/
│   └── dashboard.html     ← 대시보드 UI
├── data/                  ← SQLite DB (gitignored)
├── output/                ← MP3 임시 저장 (gitignored)
├── .env.example
└── requirements.txt
```

## 주의사항

- **notebooklm-py는 비공식 라이브러리**. Google이 내부 API를 변경하면 작동이 중단될 수 있음.
- 쿠키는 수 주마다 만료됨. 서버 로그에 인증 에러가 나면 `notebooklm login` 재실행.
- 무료 계정 기준 일일 오디오 생성 횟수에 제한이 있을 수 있음 (비공식이라 정확한 수치 미공개).
