/**
 * MyNews Radio Alexa Skill (AudioPlayer custom skill)
 *
 * 設計: docs/alexa-skill-design.md  / 追跡: Multica BEE-1123
 * 依存: ask-sdk-core, Node.js 18+ (fetch 使用)
 */
const Alexa = require('ask-sdk-core');

const PUBLIC_BASE_URL = 'https://radio.beeworks.cc';

// ---------------------------------------------------------------------------
// バックエンド連携
// ---------------------------------------------------------------------------

/** /api/episodes を叩いて公開エピソード一覧（completed & 音声あり）を取得 */
async function fetchEpisodes(category = null, limit = 10) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (category) params.set('category', category);
  const res = await fetch(`${PUBLIC_BASE_URL}/api/episodes?${params}`);
  if (!res.ok) throw new Error(`episodes API ${res.status}`);
  const json = await res.json();
  // limit 指定時は {items,total,has_next}、未指定は配列
  return Array.isArray(json) ? json : (json.items || []);
}

/** 最新の公開エピソードを1件返す（/api/episodes/latest を優先、フォールバックで一覧先頭） */
async function fetchLatestEpisode() {
  const res = await fetch(`${PUBLIC_BASE_URL}/api/episodes/latest`);
  if (res.ok) {
    const ep = await res.json();
    if (ep && ep.audio_url) return ep;
  }
  const list = await fetchEpisodes('commentary', 1);
  return list[0] || null;
}

/** audio_url(相対パス) をフルURL化 */
function toAbsoluteAudioUrl(episode) {
  if (!episode || !episode.audio_url) return null;
  return `${PUBLIC_BASE_URL}${episode.audio_url}`;
}

/** AudioPlayer.Play ディレクティブ組み立て */
function buildPlayDirective(episode) {
  const artUrl = `${PUBLIC_BASE_URL}/images/categories/${episode.type || 'general'}.png`;
  return {
    type: 'AudioPlayer.Play',
    playBehavior: 'REPLACE_ALL',
    audioItem: {
      stream: {
        token: `episode-${episode.id}`,
        url: toAbsoluteAudioUrl(episode),
        offsetInMilliseconds: 0,
      },
      metadata: {
        title: episode.title || `MyNews Radio #${episode.id}`,
        subtitle: episode.type === 'commentary' ? '解説' : 'テックニュース',
        art: { sources: [{ url: artUrl }] },
        backgroundImage: { sources: [{ url: artUrl }] },
      },
    },
  };
}

// ---------------------------------------------------------------------------
// ハンドラ
// ---------------------------------------------------------------------------

/** LaunchRequest: 最新エピソードを案内して再生確認 */
const LaunchRequestHandler = {
  canHandle(handlerInput) {
    return Alexa.getRequestType(handlerInput.requestEnvelope) === 'LaunchRequest';
  },
  async handle(handlerInput) {
    try {
      const ep = await fetchLatestEpisode();
      if (!ep) {
        return handlerInput.responseBuilder
          .speak('新しいエピソードはまだありません。')
          .getResponse();
      }
      return handlerInput.responseBuilder
        .speak(`MyNews Radio です。最新は「${ep.title}」です。再生しますか？`)
        .reprompt('再生しますか？')
        .getResponse();
    } catch (e) {
      return handlerInput.responseBuilder
        .speak('番組情報を取得できませんでした。')
        .getResponse();
    }
  },
};

/** 再生 intent: 最新エピソードを AudioPlayer.Play */
const PlayIntentHandler = {
  canHandle(handlerInput) {
    const req = handlerInput.requestEnvelope.request;
    return req.type === 'IntentRequest' && req.intent.name === 'PlayLatestIntent';
  },
  async handle(handlerInput) {
    try {
      const ep = await fetchLatestEpisode();
      if (!ep) {
        return handlerInput.responseBuilder
          .speak('再生できるエピソードがありません。')
          .getResponse();
      }
      return handlerInput.responseBuilder
        .speak(`「${ep.title}」を再生します。`)
        .addDirective(buildPlayDirective(ep))
        .withShouldEndSession(true)
        .getResponse();
    } catch (e) {
      return handlerInput.responseBuilder
        .speak('再生を開始できませんでした。')
        .getResponse();
    }
  },
};

/** PlaybackNearlyFinished: 次のエピソードを ENQUEUE（連続再生） */
const PlaybackNearlyFinishedHandler = {
  canHandle(handlerInput) {
    return handlerInput.requestEnvelope.request.type === 'AudioPlayer.PlaybackNearlyFinished';
  },
  async handle(handlerInput) {
    const request = handlerInput.requestEnvelope.request;
    const next = await fetchEpisodes('commentary', 5);
    // token 検証（重複 ENQUEUE 防止）。簡易的に次エピソードを決定
    const currentToken = request.token || '';
    const nextEpisode = next.find((e) => `episode-${e.id}` !== currentToken);
    if (!nextEpisode) {
      return handlerInput.responseBuilder.getResponse(); // 何もしない
    }
    const directive = buildPlayDirective(nextEpisode);
    directive.playBehavior = 'ENQUEUE';
    return handlerInput.responseBuilder
      .addDirective(directive)
      .getResponse();
  },
};

/** 再生状態イベント（Finish/Stopped/Failed）: 現状はログのみ */
const PlaybackEventHandlers = ['AudioPlayer.PlaybackFinished', 'AudioPlayer.PlaybackStopped', 'AudioPlayer.PlaybackFailed'].map(
  (type) => ({
    canHandle(handlerInput) {
      return handlerInput.requestEnvelope.request.type === type;
    },
    handle(handlerInput) {
      const req = handlerInput.requestEnvelope.request;
      console.error(`[${type}] token=${req.token}`, req.error || '');
      return handlerInput.responseBuilder.getResponse();
    },
  })
);

/** AMAZON.PauseIntent -> Stop */
const PauseIntentHandler = {
  canHandle(handlerInput) {
    return (
      handlerInput.requestEnvelope.request.type === 'IntentRequest' &&
      handlerInput.requestEnvelope.request.intent.name === 'AMAZON.PauseIntent'
    );
  },
  handle(handlerInput) {
    return handlerInput.responseBuilder
      .addDirective({ type: 'AudioPlayer.Stop' })
      .getResponse();
  },
};

/** AMAZON.ResumeIntent -> 再開（前回トークンは簡易実装） */
const ResumeIntentHandler = {
  canHandle(handlerInput) {
    return (
      handlerInput.requestEnvelope.request.type === 'IntentRequest' &&
      handlerInput.requestEnvelope.request.intent.name === 'AMAZON.ResumeIntent'
    );
  },
  async handle(handlerInput) {
    const ep = await fetchLatestEpisode();
    if (!ep) return handlerInput.responseBuilder.speak('再開できるエピソードがありません。').getResponse();
    const directive = buildPlayDirective(ep);
    return handlerInput.responseBuilder
      .addDirective(directive)
      .withShouldEndSession(true)
      .getResponse();
  },
};

/** AMAZON.CancelIntent / StopIntent */
const CancelIntentHandler = {
  canHandle(handlerInput) {
    return (
      handlerInput.requestEnvelope.request.type === 'IntentRequest' &&
      ['AMAZON.CancelIntent', 'AMAZON.StopIntent'].includes(
        handlerInput.requestEnvelope.request.intent.name
      )
    );
  },
  handle(handlerInput) {
    return handlerInput.responseBuilder
      .addDirective({ type: 'AudioPlayer.Stop' })
      .speak('終了します。')
      .getResponse();
  },
};

/** フォールバック */
const FallbackIntentHandler = {
  canHandle(handlerInput) {
    return (
      handlerInput.requestEnvelope.request.type === 'IntentRequest' &&
      handlerInput.requestEnvelope.request.intent.name === 'AMAZON.FallbackIntent'
    );
  },
  handle(handlerInput) {
    return handlerInput.responseBuilder
      .speak('再生、一時停止、再開、次へが使えます。')
      .reprompt('どうしますか？')
      .getResponse();
  },
};

const ErrorHandler = {
  canHandle() {
    return true;
  },
  handle(handlerInput, error) {
    console.error('=== Skill Error ===', error);
    return handlerInput.responseBuilder
      .speak('エラーが発生しました。もう一度お試しください。')
      .getResponse();
  },
};

exports.handler = Alexa.SkillBuilders.custom()
  .addRequestHandlers(
    LaunchRequestHandler,
    PlayIntentHandler,
    PlaybackNearlyFinishedHandler,
    ...PlaybackEventHandlers,
    PauseIntentHandler,
    ResumeIntentHandler,
    CancelIntentHandler,
    FallbackIntentHandler
  )
  .addErrorHandlers(ErrorHandler)
  .lambda();
