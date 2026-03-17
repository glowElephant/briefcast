# Briefcast

매일 아침, 원하는 주제로 한국어 AI 팟캐스트를 자동 생성하는 서버.

Google News, YouTube, X(Twitter), DuckDuckGo에서 최근 24시간 뉴스를 수집하고, NotebookLM으로 한국어 팟캐스트 오디오를 생성하여 Google Drive에 저장한다.

## 기능

- **웹 대시보드** — 주제 관리 (추가/수정/삭제/토글), 에피소드 히스토리
- **다중 소스 수집** — Google News RSS, YouTube, X(Twitter), DuckDuckGo 뉴스
- **한국어 팟캐스트** — NotebookLM Audio Overview (Deep Dive, Brief, Critique, Debate)
- **Google Drive 자동 업로드** — 날짜별 폴더 자동 생성
- **스케줄러** — 매일 지정 시간 자동 실행 (대시보드에서 변경 가능)
- **수동 실행** — 대시보드에서 Run 버튼으로 즉시 실행
- **설정 관리** — 리포트 시간, 오디오 포맷/길이를 대시보드에서 설정

## 파이프라인

```
[매일 06:00 KST] 스케줄러
    │
    ├─ 1. 뉴스 수집 (최근 24시간)
    │   ├─ Google News RSS (ko/en)
    │   ├─ DuckDuckGo 뉴스 검색
    │   ├─ YouTube 영상 검색
    │   └─ X(Twitter) 인기 게시물
    │
    ├─ 2. 본문 추출 (trafilatura)
    │
    ├─ 3. NotebookLM 오디오 생성 (한국어)
    │
    └─ 4. Google Drive 업로드
```

## 오디오 설정

| 포맷 | 설명 |
|------|------|
| **DEEP_DIVE** | 심층 분석 (기본값) |
| **BRIEF** | 간략 요약 |
| **CRITIQUE** | 비판적 분석 |
| **DEBATE** | 토론 형식 |

| 길이 | 예상 시간 |
|------|-----------|
| **SHORT** | 5~10분 |
| **DEFAULT** | 10~20분 |
| **LONG** | 20~30분 |

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
pip install "notebooklm-py[browser]"
playwright install chromium
notebooklm login
```

- 브라우저가 열리면 Google 계정으로 로그인 → NotebookLM 홈페이지 로드 후 Enter
- 쿠키는 `~/.notebooklm/storage_state.json`에 저장됨
- **수 주마다 만료** — 만료 시 `notebooklm login` 재실행

### 2. Google Drive OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. 프로젝트 생성 (또는 기존 프로젝트 사용)
3. **APIs & Services > Library** → "Google Drive API" 검색 → **Enable**
4. **APIs & Services > Credentials** → **Create Credentials > OAuth client ID**
   - Application type: **Desktop app**
5. JSON 다운로드 → 프로젝트 루트에 `credentials.json`으로 저장
6. **OAuth consent screen** 설정:
   - User type: External (테스트 중 상태 OK)
   - Test users: 본인 Gmail 추가

첫 실행 시 브라우저가 열리며 권한 승인 → `token.json` 자동 생성.

### 3. Google Drive 폴더

1. Google Drive에서 폴더 생성 (예: `Briefcast`) — **비공개 유지**
2. 폴더 URL에서 ID 복사: `https://drive.google.com/drive/folders/{FOLDER_ID}`
3. `.env`에 `GOOGLE_DRIVE_FOLDER_ID={FOLDER_ID}` 설정

## 설치

```bash
cd C:/Git/briefcast

# 가상환경
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
# 또는 CMD: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 편집하여 GOOGLE_DRIVE_FOLDER_ID 설정
```

## 실행

```bash
python server.py
```

대시보드: http://localhost:8585

Server Manager(`http://localhost:9000`)에 등록되어 있으면 자동 시작됨.

## 설정

### .env (서버 설정)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 서버 바인드 주소 |
| `PORT` | `8585` | 서버 포트 |
| `GOOGLE_DRIVE_FOLDER_ID` | (필수) | Drive 업로드 대상 폴더 ID |
| `MAX_ARTICLES_PER_TOPIC` | `10` | 주제당 최대 수집 기사 수 |
| `ARTICLE_FETCH_DELAY` | `1.5` | 기사 수집 간 딜레이 (초) |

### 대시보드 Settings (런타임 설정)

| 항목 | 기본값 | 설명 |
|------|--------|------|
| Report Time | `06:00` | 매일 자동 실행 시각 (KST) |
| Format | `DEEP_DIVE` | 오디오 포맷 |
| Length | `DEFAULT` | 오디오 길이 |

## 구조

```
briefcast/
├── server.py              ← FastAPI 서버 + 대시보드 + Settings API
├── core/
│   ├── collector.py       ← 뉴스 수집 (RSS + YouTube + X + 검색 + 본문 추출)
│   ├── podcast.py         ← NotebookLM 한국어 오디오 생성
│   ├── drive.py           ← Google Drive 업로드
│   ├── database.py        ← SQLite DB (topics, episodes, settings)
│   └── scheduler.py       ← APScheduler + 파이프라인 오케스트레이션
├── templates/
│   └── dashboard.html     ← 대시보드 UI (주제 관리 + 설정 + 히스토리)
├── data/                  ← SQLite DB (gitignored)
├── output/                ← MP3 임시 저장 (gitignored)
├── credentials.json       ← Google OAuth (gitignored)
├── token.json             ← OAuth 토큰 (gitignored, 자동 생성)
├── .env                   ← 환경변수 (gitignored)
├── .env.example
└── requirements.txt
```

## 주의사항

- **notebooklm-py는 비공식 라이브러리**. Google이 내부 API를 변경하면 작동이 중단될 수 있음.
- 쿠키는 **수 주마다 만료**됨. 서버 로그에 인증 에러가 나면 `notebooklm login` 재실행.
- 무료 계정 기준 일일 오디오 생성 횟수에 제한이 있을 수 있음 (비공식이라 정확한 수치 미공개).
- `credentials.json`, `token.json`, `.env`는 gitignored — 새 환경에서는 재설정 필요.
