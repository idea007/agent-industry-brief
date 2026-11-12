const HAN_TO_LATIN_OR_NUMBER =
  /([\p{Script=Han}])([A-Za-z0-9])/gu;
const LATIN_OR_NUMBER_TO_HAN =
  /([A-Za-z0-9])([\p{Script=Han}])/gu;

export function normalizeMixedTextSpacing(value) {
  return value
    .replace(HAN_TO_LATIN_OR_NUMBER, "$1 $2")
    .replace(LATIN_OR_NUMBER_TO_HAN, "$1 $2");
}
