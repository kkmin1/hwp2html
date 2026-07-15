# hwp2html

Windows에 설치된 한컴오피스를 이용하여 `.hwp` 문서를 HML로 추출한 뒤, 본문·수식·표·그림을 웹에서 볼 수 있는 HTML로 변환하는 도구입니다.

사용자가 HML 파일을 미리 만들 필요는 없습니다. 통합 실행기인 `hwp2html.py`가 다음 과정을 한 번에 수행합니다.

```text
HWP
 ├─ 한컴오피스 자동화 → HML
 ├─ 한컴오피스 네이티브 HTML → 변환 실패 그림의 GIF 폴백 원본
 └─ HML 분석
      ├─ 본문·문자 모양 → HTML
      ├─ 한글 수식 스크립트 → LaTeX/KaTeX
      ├─ TABLE → HTML table
      ├─ 객체 그림 → GTree → SVG
      └─ 일반 이미지 → media 파일
```

## 빠른 시작

```powershell
python C:\project\hwp2html\hwp2html.py "C:\문서\입력.hwp" -o "C:\문서\출력폴더"
```

`-o`를 생략하면 입력 파일 옆에 `<파일명>_html` 폴더가 만들어집니다.

```powershell
python C:\project\hwp2html\hwp2html.py "C:\문서\입력.hwp"
```

## 주요 기능

### HWP부터 HTML까지 한 번에 변환

- 한컴오피스 COM 자동화를 통해 HWP를 HML(`HWPML2X`)로 자동 추출
- 변환 실패 개체의 폴백을 위해 한컴 네이티브 HTML도 함께 생성
- HML, HTML, 미디어와 변환 보고서를 하나의 출력 폴더에 정리
- 처리 결과를 표준 출력에 JSON으로 표시

### 본문과 문자 모양

- 본문 문단과 정렬
- 제목 수준 추정
- 굵게 표시된 글머리표 평문을 제목으로 오인하지 않도록 처리
- 위첨자와 아래첨자
- 문단과 표 사이의 브라우저 기본 여백 보정
- 한글 표의 기본 글자 크기에 맞춘 표 렌더링

### 수식

- 한글 수식 스크립트를 LaTeX 문법으로 변환
- 분수, 첨자, 적분, 행렬, pile, 그리스 문자와 일반적인 수식 명령 처리
- 고딕 계열 수식의 굵기 처리
- HTML에서 KaTeX 0.16.9로 렌더링
- KaTeX는 jsDelivr CDN에서 로드하므로 최초 표시 시 인터넷 연결 필요

### 표

- 행과 열 구조
- `rowspan`, `colspan` 셀 병합
- HWPUNIT 기반 열 너비와 행 높이 계산
- 셀 내부 여백과 세로·가로 정렬
- 열린 테두리, 실선, 점선, 파선, 이중선
- 셀 단색 배경과 그라데이션
- 표 셀 안의 굵은 글자를 문서 제목으로 오인하지 않도록 별도 렌더링
- 잘못된 `<p><table>` 중첩 방지

표 렌더링은 `hml_table_renderer.py`가 담당합니다.

### 객체 그림과 그래프

- HML의 `CONTAINER` 객체를 편집 가능한 GTree JSON으로 변환
- GTree를 브라우저 표시용 SVG로 자동 렌더링
- 선, 화살표, 사각형, 타원, 다각형, 곡선, 호, 텍스트 등 처리
- HWP의 회전·크기 조절·이동 변환 행렬을 조합하여 객체 상대 위치 복원
- HWP 호 좌표계와 절대 축 좌표 보정
- SVG의 불필요한 상하 여백 축소
- SVG 재구성에 실패하면 한컴 네이티브 HTML이 만든 GIF로 자동 폴백

성공한 객체 그림은 HTML 표시용 `.svg`와 재편집용 `.gtree`가 모두 `media` 폴더에 저장됩니다.

### 일반 삽입 이미지

- HML의 `BINDATA` 및 `BINITEM`을 이용해 이미지 형식과 데이터를 복원
- HTML 옆 `media` 폴더에 파일로 저장
- HTML에서는 상대 경로로 참조

## 요구사항

### 운영체제와 한컴오피스

- Windows
- 한컴오피스 한글 설치 필요
- HWP 문서를 열고 HML 및 HTML로 저장할 수 있는 한글 버전 필요

HWP → HML 단계는 한컴오피스 COM 자동화를 사용하므로, 한컴오피스가 없는 환경에서는 통합 변환을 실행할 수 없습니다. 이미 HML이 있다면 `hml2html.py`만 별도로 사용할 수 있습니다.

### Python

- Python 3
- [`hwpapi`](https://github.com/JunDamin/hwpapi)
- `pywin32` (`hwpapi` 의존성으로 설치됨)

현재 개발 환경에서 확인한 버전은 `hwpapi 3.0.0`입니다.

```powershell
python -m pip install hwpapi
```

HTML 변환 핵심 모듈은 Python 표준 라이브러리를 중심으로 작성되어 있으며, 별도의 서버를 실행할 필요가 없습니다.

## 출력 구조

예를 들어 `경제학.hwp`를 `경제학_html` 폴더로 변환하면 다음과 같은 파일이 생성됩니다.

```text
경제학_html/
├─ 경제학.html
├─ 경제학.hml
├─ conversion-report.json
├─ media/
│  ├─ 경제학_graph_001.gtree
│  ├─ 경제학_graph_001.svg
│  ├─ 경제학_graph_002_fallback.gif
│  └─ 경제학_001.png
└─ native_reference/
   ├─ reference.html
   └─ ... 한컴이 내보낸 참조 리소스
```

### `conversion-report.json`

변환 후 다음 정보를 기록합니다.

- 원본 HWP 경로
- 최종 HTML 경로
- 중간 HML 경로
- 네이티브 참조 HTML 경로
- 객체 그림 수
- 생성된 GTree/SVG 수
- GIF 폴백 수
- 수식 수
- 각주 수
- 포함 이미지 수

## 명령행 사용법

```text
usage: hwp2html.py [-h] [-o OUTPUT] source

positional arguments:
  source                입력 HWP 파일

options:
  -h, --help            도움말
  -o, --output OUTPUT   출력 폴더
```

경로에 공백이나 한글이 있으면 따옴표로 감싸는 것이 안전합니다.

```powershell
python hwp2html.py "C:\내 문서\거시경제학 응용.hwp" -o "C:\내 문서\거시경제학 HTML"
```

## 개별 도구

일반 사용자는 `hwp2html.py`만 실행하면 됩니다. 아래 도구들은 중간 결과를 직접 다루거나 디버깅할 때 사용합니다.

### `hml2html.py`

이미 만들어진 HML을 HTML로 변환하는 핵심 변환기입니다.

```powershell
python hml2html.py input.hml output.html
```

HWP를 직접 입력받지 않으며, HWP → HML 추출과 GIF 폴백 준비까지 포함하려면 `hwp2html.py`를 사용해야 합니다.

### `hml_table_renderer.py`

HML 표의 열 너비, 행 높이, 셀 병합, 내부 여백, 테두리와 배경을 CSS로 변환하는 보조 모듈입니다. 단독 실행용이 아닙니다.

### `hml_to_gtree.py`

HML 객체 그림을 GTree JSON으로 변환합니다.

```powershell
python hml_to_gtree.py graph.hml graph.gtree
```

`.gtree`는 전용 바이너리가 아니라 편집 가능한 JSON 파일입니다.

### `gtree_to_svg.py`

GTree JSON을 SVG로 렌더링합니다. 통합 변환에서는 자동 호출됩니다.

```powershell
python gtree_to_svg.py graph.gtree graph.svg
```

### `gtree_to_tikz.py`

GTree를 TikZ 코드로 변환하는 별도 후처리 도구입니다.

```powershell
python gtree_to_tikz.py graph.gtree graph.tex
```

### `resume_hml_to_html.py`

페이지 크기와 레이아웃 충실도를 실험하기 위해 남겨 둔 보조 변환기입니다. 기본 전체 변환 경로는 `hwp2html.py`와 `hml2html.py`입니다.

## 변환 전략과 폴백

객체 그림은 가능한 한 수정 가능한 상태를 유지하기 위해 먼저 GTree/SVG 재구성을 시도합니다.

1. HML `CONTAINER` 분석
2. 객체별 좌표·크기·회전·스타일을 GTree로 변환
3. GTree에서 SVG 생성
4. 성공 시 `.gtree`와 `.svg` 저장
5. 실패 시 한컴 네이티브 HTML에서 추출한 GIF 사용

SVG는 텍스트와 도형을 수정할 수 있다는 장점이 있고, GIF 폴백은 원본 표시 충실도를 우선합니다.

## 알려진 제한사항

- HWP 자동 변환은 Windows와 설치된 한컴오피스에 의존합니다.
- 한컴 내부 객체 형식의 모든 도형 효과를 완전히 지원하는 것은 아닙니다.
- 지원하지 않는 복잡한 객체 그림은 GIF로 폴백될 수 있습니다.
- KaTeX CDN을 사용하므로 오프라인에서는 수식 원문이 표시되고 KaTeX 조판이 적용되지 않을 수 있습니다.
- 한컴과 브라우저의 글꼴 엔진이 달라 일부 문서에서 미세한 글자 폭·줄바꿈 차이가 발생할 수 있습니다.
- 변환 결과는 원본 보존본이 아니라 웹 표시 및 편집을 위한 HTML이므로, 중요한 문서는 원본 HWP도 함께 보관해야 합니다.

## 문제 해결

### `hwpapi` 또는 COM 관련 오류

1. 한컴오피스 한글이 정상 실행되는지 확인합니다.
2. `python -m pip show hwpapi`로 설치 여부를 확인합니다.
3. Python과 한컴오피스가 현재 Windows 사용자 계정에서 실행 가능한지 확인합니다.

### 수식이 조판되지 않음

브라우저 개발자 도구에서 KaTeX CDN 로딩 여부를 확인합니다. 폐쇄망에서는 KaTeX 파일을 로컬로 내려받아 HTML 템플릿의 CDN 경로를 바꿔야 합니다.

### 그림이 GIF로 출력됨

해당 객체를 SVG/GTree로 재구성하지 못해 충실도 우선 폴백이 작동한 것입니다. `conversion-report.json`의 `gif_fallbacks` 값을 확인하십시오.

### HTML만 다른 위치로 옮겼더니 이미지가 보이지 않음

HTML은 `media` 폴더를 상대 경로로 참조합니다. HTML과 `media` 폴더를 함께 이동해야 합니다.

## 최근 주요 갱신

- HWP → HML → HTML 통합 실행기 `hwp2html.py` 추가
- HML 수식의 LaTeX/KaTeX 변환 보강
- 위첨자·아래첨자 처리 추가
- 객체 그림의 GTree/SVG 자동 생성 및 GIF 폴백 추가
- HWP 변환 행렬과 호 좌표계 보정으로 그래프 교차점·점선 상대 위치 개선
- SVG 바운딩 박스와 문장 안 그림의 상하 여백 축소
- 표 행·열 병합, 크기, 패딩, 정렬, 테두리, 배경과 그라데이션 처리 보강
- 셀 내부 굵은 문장을 제목으로 오인하는 문제 수정
- 글머리표 평문을 제목으로 오인하여 줄 간격이 커지는 문제 수정
- 표 글꼴 크기와 표 사이 여백 보정
- 변환 통계 JSON 보고서 추가

## 참고 자료

- [한컴 기술 블로그: Python을 이용한 HWP 파싱](https://tech.hancom.com/python-hwp-parsing-2)
- [rhwp](https://github.com/edwardkim/rhwp)
- [hwpapi](https://github.com/JunDamin/hwpapi)

## 라이선스

저장소에 별도 라이선스 파일이 추가되기 전까지는 사용·배포 조건을 저장소 소유자에게 확인하십시오.
