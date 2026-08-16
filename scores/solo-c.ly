\version "2.24.0"
\include "layout.ily"
\include "solo.ily"

\header {
  title    = \cyr #4 "Соло в C"
  subtitle = \cyr #0 "Курс \"Буги-вуги\" 2.0 Урок 5"
  composer = \cyr #0 "Юлия Шишкина"
  tagline  = ##f
}

%% авторский оригинал — служит эталоном для сверки
\score { \makeScore \rightC \leftC \layout { } }
