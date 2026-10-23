{
	const $ = django.jQuery;

	$.fn.djangoCustomSelect2 = function () {
		$.each(this, (_index, element) => {
			if (element.id.match(/__prefix__/)) {
				return;
			}

			if ($(element).hasClass("select2-hidden-accessible")) {
				return;
			}

			const filterForm = $(element).closest('#filter-form');
			$(element).select2({
				...(filterForm.length ? { dropdownParent: filterForm } : {}),
			});

			if (element.closest("#changelist-filter") && !element.form) {
				$(element).on("change", () => {
					const url = new URL(window.location.href);
					url.searchParams.delete(element.name);

					for (const option of element.selectedOptions) {
						if (option.value !== "") {
							url.searchParams.append(element.name, option.value);
						}
					}

					// A changed filter must start at the first page of its results.
					url.searchParams.delete("p");
					window.location.assign(url);
				});
			}
		});

		return this;
	};

	$.fn.djangoFilterSelect2 = function () {
		$.each(this, (_index, element) => {
			const formParent = this.closest('#filter-form');

			$(element).select2({
				closeOnSelect: !element.multiple,
				...(formParent.length ? { dropdownParent: formParent } : {}),
				ajax: {
					data: (params) => {
						return {
							term: params.term,
							page: params.page,
							app_label: element.dataset.appLabel,
							model_name: element.dataset.modelName,
							field_name: element.dataset.fieldName,
						};
					},
				},
			});
		});

		return this;
	};

	$(() => {
		$(".unfold-admin-autocomplete").djangoCustomSelect2();

		$(".unfold-filter-autocomplete").djangoFilterSelect2();

		document.addEventListener("formset:added", (event) => {
			$(event.target).find(".unfold-admin-autocomplete").djangoCustomSelect2();
		});
	});
}
