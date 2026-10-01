import dayjs from 'dayjs';
import isToday from 'dayjs/plugin/isToday';
import isYesterday from 'dayjs/plugin/isYesterday';
import localizedFormat from 'dayjs/plugin/localizedFormat';

dayjs.extend(isToday);
dayjs.extend(isYesterday);
dayjs.extend(localizedFormat);

export const formatDate = (inputDate) => {
	const date = dayjs(inputDate);

	if (date.isToday()) {
		return `Today at ${date.format('LT')}`;
	} else if (date.isYesterday()) {
		return `Yesterday at ${date.format('LT')}`;
	} else {
		return `${date.format('L')} at ${date.format('LT')}`;
	}
};
