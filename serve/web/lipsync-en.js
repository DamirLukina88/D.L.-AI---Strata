// serve/web/lipsync-en.js - English words to mouth shapes (Oculus visemes) with relative durations, for Ray's face.
// Ported from TalkingHead's modules/lipsync-en.mjs (https://github.com/met4citizen/TalkingHead, commit 166b443a):
// the letter-to-sound rules, the viseme durations and wordsToVisemes(); its number and symbol expansion is left out.
//
// MIT License. Copyright (c) 2023-2024 Mika Suominen. Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software
// without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute,
// sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so,
// subject to the following conditions: The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE
// AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
// SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"use strict";

const LipsyncEn = (() => {
  const rules = {
    'A': [
      "[A] =aa", " [ARE] =aa RR", " [AR]O=aa RR", "[AR]#=E RR",
      " ^[AS]#=E SS", "[A]WA=aa", "[AW]=aa", " :[ANY]=E nn I",
      "[A]^+#=E", "#:[ALLY]=aa nn I", " [AL]#=aa nn", "[AGAIN]=aa kk E nn",
      "#:[AG]E=I kk", "[A]^+:#=aa", ":[A]^+ =E", "[A]^%=E",
      " [ARR]=aa RR", "[ARR]=aa RR", " :[AR] =aa RR", "[AR] =E",
      "[AR]=aa RR", "[AIR]=E RR", "[AI]=E", "[AY]=E", "[AU]=aa",
      "#:[AL] =aa nn", "#:[ALS] =aa nn SS", "[ALK]=aa kk", "[AL]^=aa nn",
      " :[ABLE]=E PP aa nn", "[ABLE]=aa PP aa nn", "[ANG]+=E nn kk", "[A]=aa"
    ],

    'B': [
      " [BE]^#=PP I", "[BEING]=PP I I nn", " [BOTH] =PP O TH",
      " [BUS]#=PP I SS", "[BUIL]=PP I nn", "[B]=PP"
    ],

    'C': [
      " [CH]^=kk", "^E[CH]=kk", "[CH]=CH", " S[CI]#=SS aa",
      "[CI]A=SS", "[CI]O=SS", "[CI]EN=SS", "[C]+=SS",
      "[CK]=kk", "[COM]%=kk aa PP", "[C]=kk"
    ],

    'D': [
      "#:[DED] =DD I DD", ".E[D] =DD", "#^:E[D] =DD", " [DE]^#=DD I",
      " [DO] =DD U", " [DOES]=DD aa SS", " [DOING]=DD U I nn",
      " [DOW]=DD aa", "[DU]A=kk U", "[D]=DD"
    ],

    'E': [
      "#:[E] =", "'^:[E] =", " :[E] =I", "#[ED] =DD", "#:[E]D =",
      "[EV]ER=E FF", "[E]^%=I", "[ERI]#=I RR I", "[ERI]=E RR I",
      "#:[ER]#=E", "[ER]#=E RR", "[ER]=E", " [EVEN]=I FF E nn",
      "#:[E]W=", "@[EW]=U", "[EW]=I U", "[E]O=I", "#:&[ES] =I SS",
      "#:[E]S =", "#:[ELY] =nn I", "#:[EMENT]=PP E nn DD", "[EFUL]=FF U nn",
      "[EE]=I", "[EARN]=E nn", " [EAR]^=E", "[EAD]=E DD", "#:[EA] =I aa",
      "[EA]SU=E", "[EA]=I", "[EIGH]=E", "[EI]=I", " [EYE]=aa", "[EY]=I",
      "[EU]=I U", "[E]=E"
    ],

    'F': [
      "[FUL]=FF U nn", "[F]=FF"
    ],

    'G': [
      "[GIV]=kk I FF", " [G]I^=kk", "[GE]T=kk E", "SU[GGES]=kk kk E SS",
      "[GG]=kk", " B#[G]=kk", "[G]+=kk", "[GREAT]=kk RR E DD",
      "#[GH]=", "[G]=kk"
    ],

    'H': [
      " [HAV]=I aa FF", " [HERE]=I I RR", " [HOUR]=aa EE", "[HOW]=I aa",
      "[H]#=I", "[H]="
    ],

    'I': [
      " [IN]=I nn", " [I] =aa", "[IN]D=aa nn", "[IER]=I E",
      "#:R[IED] =I DD", "[IED] =aa DD", "[IEN]=I E nn", "[IE]T=aa E",
      " :[I]%=aa", "[I]%=I", "[IE]=I", "[I]^+:#=I", "[IR]#=aa RR",
      "[IZ]%=aa SS", "[IS]%=aa SS", "[I]D%=aa", "+^[I]^+=I",
      "[I]T%=aa", "#^:[I]^+=I", "[I]^+=aa", "[IR]=E", "[IGH]=aa",
      "[ILD]=aa nn DD", "[IGN] =aa nn", "[IGN]^=aa nn", "[IGN]%=aa nn",
      "[IQUE]=I kk", "[I]=I"
    ],

    'J': [
      "[J]=kk"
    ],

    'K': [
      " [K]N=", "[K]=kk"
    ],

    'L': [
      "[LO]C#=nn O", "L[L]=", "#^:[L]%=aa nn", "[LEAD]=nn I DD", "[L]=nn"
    ],

    'M': [
      "[MOV]=PP U FF", "[M]=PP"
    ],

    'N': [
      "E[NG]+=nn kk", "[NG]R=nn kk", "[NG]#=nn kk", "[NGL]%=nn kk aa nn",
      "[NG]=nn", "[NK]=nn kk", " [NOW] =nn aa", "[N]=nn"
    ],

    'O': [
      "[OF] =aa FF", "[OROUGH]=E O", "#:[OR] =E", "#:[ORS] =E SS",
      "[OR]=aa RR", " [ONE]=FF aa nn", "[OW]=O", " [OVER]=O FF E",
      "[OV]=aa FF", "[O]^%=O", "[O]^EN=O", "[O]^I#=O", "[OL]D=O nn",
      "[OUGHT]=aa DD", "[OUGH]=aa FF", " [OU]=aa", "H[OU]S#=aa",
      "[OUS]=aa SS", "[OUR]=aa RR", "[OULD]=U DD", "^[OU]^L=aa",
      "[OUP]=U OO", "[OU]=aa", "[OY]=O", "[OING]=O I nn", "[OI]=O",
      "[OOR]=aa RR", "[OOK]=U kk", "[OOD]=U DD", "[OO]=U", "[O]E=O",
      "[O] =O", "[OA]=O", " [ONLY]=O nn nn I", " [ONCE]=FF aa nn SS",
      "[ON'T]=O nn DD", "C[O]N=aa", "[O]NG=aa", " ^:[O]N=aa",
      "I[ON]=aa nn", "#:[ON] =aa nn", "#^[ON]=aa nn", "[O]ST =O",
      "[OF]^=aa FF", "[OTHER]=aa TH E", "[OSS] =aa SS", "#^:[OM]=aa PP",
      "[O]=aa"
    ],

    'P': [
      "[PH]=FF", "[PEOP]=PP I PP", "[POW]=PP aa", "[PUT] =PP U DD",
      "[P]=PP"
    ],

    'Q': [
      "[QUAR]=kk FF aa RR", "[QU]=kk FF", "[Q]=kk"
    ],

    'R': [
      " [RE]^#=RR I", "[R]=RR"
    ],

    'S': [
      "[SH]=SS", "#[SION]=SS aa nn", "[SOME]=SS aa PP", "#[SUR]#=SS E",
      "[SUR]#=SS E", "#[SU]#=SS U", "#[SSU]#=SS U", "#[SED] =SS DD",
      "#[S]#=SS", "[SAID]=SS E DD", "^[SION]=SS aa nn", "[S]S=",
      ".[S] =SS", "#:.E[S] =SS", "#^:##[S] =SS", "#^:#[S] =SS",
      "U[S] =SS", " :#[S] =SS", " [SCH]=SS kk", "[S]C+=",
      "#[SM]=SS PP", "#[SN]'=SS aa nn", "[S]=SS"
    ],

    'T': [
      " [THE] =TH aa", "[TO] =DD U", "[THAT] =TH aa DD", " [THIS] =TH I SS",
      " [THEY]=TH E", " [THERE]=TH E RR", "[THER]=TH E", "[THEIR]=TH E RR",
      " [THAN] =TH aa nn", " [THEM] =TH E PP", "[THESE] =TH I SS",
      " [THEN]=TH E nn", "[THROUGH]=TH RR U", "[THOSE]=TH O SS",
      "[THOUGH] =TH O", " [THUS]=TH aa SS", "[TH]=TH", "#:[TED] =DD I DD",
      "S[TI]#N=CH", "[TI]O=SS", "[TI]A=SS", "[TIEN]=SS aa nn",
      "[TUR]#=CH E", "[TU]A=CH U", " [TWO]=DD U", "[T]=DD"
    ],

    'U': [
      " [UN]I=I U nn", " [UN]=aa nn", " [UPON]=aa PP aa nn",
      "@[UR]#=U RR", "[UR]#=I U RR", "[UR]=E", "[U]^ =aa",
      "[U]^^=aa", "[UY]=aa", " G[U]#=", "G[U]%=", "G[U]#=FF",
      "#N[U]=I U", "@[U]=I", "[U]=I U"
    ],

    'V': [
      "[VIEW]=FF I U", "[V]=FF"
    ],

    'W': [
      " [WERE]=FF E", "[WA]S=FF aa", "[WA]T=FF aa", "[WHERE]=FF E RR",
      "[WHAT]=FF aa DD", "[WHOL]=I O nn", "[WHO]=I U", "[WH]=FF",
      "[WAR]=FF aa RR", "[WOR]^=FF E", "[WR]=RR", "[W]=FF"
    ],

    'X': [
      " [X]=SS", "[X]=kk SS"
    ],

    'Y': [
      "[YOUNG]=I aa nn", " [YOU]=I U", " [YES]=I E SS", " [Y]=I",
      "#^:[Y] =I", "#^:[Y]I=I", " :[Y] =aa", " :[Y]#=aa",
      " :[Y]^+:#=I", " :[Y]^#=I", "[Y]=I"
    ],

    'Z': [
      "[Z]=SS"
    ]
  };

  const ops = {
    '#': '[AEIOUY]+', // One or more vowels AEIOUY
    // This one is not used: "'": '[BCDFGHJKLMNPQRSTVWXZ]+', // One or more consonants BCDFGHJKLMNPQRSTVWXZ
    '.': '[BDVGJLMNRWZ]', // One voiced consonant BDVGJLMNRWZ
    // This one is not used: '$': '[BDVGJLMNRWZ][EI]', // One consonant followed by E or I
    '%': '(?:ER|E|ES|ED|ING|ELY)', // One of ER, E, ES, ED, ING, ELY
    '&': '(?:[SCGZXJ]|CH|SH)', // One of S, C, G, Z, X, J, CH, SH
    '@': '(?:[TSRDLZNJ]|TH|CH|SH)', // One of T, S, R, D, L, Z, N, J, TH, CH, SH
    '^': '[BCDFGHJKLMNPQRSTVWXZ]', // One consonant BCDFGHJKLMNPQRSTVWXZ
    '+': '[EIY]', // One of E, I, Y
    ':': '[BCDFGHJKLMNPQRSTVWXZ]*', // Zero or more consonants BCDFGHJKLMNPQRSTVWXZ
    ' ': '\\b' // Start/end of the word
  };

  // Convert rules to regex
  Object.keys(rules).forEach( key => {
    rules[key] = rules[key].map( rule => {
      const posL = rule.indexOf('[');
      const posR = rule.indexOf(']');
      const posE = rule.indexOf('=');
      const strLeft = rule.substring(0,posL);
      const strLetters = rule.substring(posL+1,posR);
      const strRight = rule.substring(posR+1,posE);
      const strVisemes = rule.substring(posE+1);

      const o = { regex: '', move: 0, visemes: [] };

      let exp = '';
      exp += [...strLeft].map( x => ops[x] || x ).join('');
      const ctxLetters = [...strLetters];
      ctxLetters[0] = ctxLetters[0].toLowerCase();
      exp += ctxLetters.join('');
      o.move = ctxLetters.length;
      exp += [...strRight].map( x => ops[x] || x ).join('');
      o.regex = new RegExp(exp);

      if ( strVisemes.length ) {
        strVisemes.split(' ').forEach( viseme => {
          o.visemes.push(viseme);
        });
      }

      return o;
    });
  });

  // Viseme durations in relative unit (1=average)
  // TODO: Check for statistics for English
  const visemeDurations = {
    'aa': 0.95, 'E': 0.90, 'I': 0.92, 'O': 0.96, 'U': 0.95, 'PP': 1.08,
    'SS': 1.23, 'TH': 1, 'DD': 1.05, 'FF': 1.00, 'kk': 1.21, 'nn': 0.88,
    'RR': 0.88, 'DD': 1.05, 'sil': 1
  };

  // Pauses in relative units (1=average)
  const specialDurations = { ' ': 1, ',': 3, '-':0.5, "'":0.5 };


  function wordsToVisemes(w) {
    let o = { words: w.toUpperCase(), visemes: [], times: [], durations: [], i:0 };
    let t = 0;

    const chars = [...o.words];
    while( o.i < chars.length ) {
      const c = chars[o.i];
      const ruleset = rules[c];
      if ( ruleset ) {
        for(let i=0; i<ruleset.length; i++) {
          const rule = ruleset[i];
          const test = o.words.substring(0, o.i) + c.toLowerCase() + o.words.substring(o.i+1);
          let matches = test.match(rule.regex);
          if ( matches ) {
            rule.visemes.forEach( viseme => {
              if ( o.visemes.length && o.visemes[ o.visemes.length - 1 ] === viseme ) {
                const d = 0.7 * (visemeDurations[viseme] || 1);
                o.durations[ o.durations.length - 1 ] += d;
                t += d;
              } else {
                const d = visemeDurations[viseme] || 1;
                o.visemes.push( viseme );
                o.times.push(t);
                o.durations.push( d );
                t += d;
              }
            })
            o.i += rule.move;
            break;
          }
        }
      } else {
        o.i++;
        t += specialDurations[c] || 0;
      }
    }

    return o;
  }

  return {wordsToVisemes, visemeDurations};
})();
