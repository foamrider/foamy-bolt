// Exercise the kit's real substitution function with catalog data in pure tests.
const I18n = require('../kit/node-loader.cjs').load('FoamyI18nText');
const en = require('../i18n/en.json');
const no = require('../i18n/no.json');
function text(key, language, values) {
  const catalog = language === 'no' || language === 'nb' ? no : en;
  return I18n.translator(catalog, en).t(key, values);
}
module.exports = { text, no, en, norwegian: no, nb: no };
