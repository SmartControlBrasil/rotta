

(function ($) {
	/* "use strict" */

	var dzChartlist = function () {

		var screenWidth = $(window).width();
		let draw = Chart.controllers.line.__super__.draw; //draw shadow

		var OverviewChart = function () {
			if ($('#overview-chart').length > 0) {
				var options = {
					series: [37.5, 7.8, 12.5, 5.2, 19, 18],
					chart: {
						type: 'donut',
						parentHeightOffset: 0,
						sparkline: {
							enabled: true,
						},
					},
					colors: ["var(--primary)", "#F89D16", "#313949", "#21C68A", "#FF7A59", "#E9EDF5"],
					legend: {
						show: false,
					},
					stroke: {
						width: 0,
					},
					dataLabels: {
						enabled: false,
					},
					plotOptions: {
						pie: {
							size: 200,
							donut: {
								labels: {

									show: true,
									name: {
										show: false,
									},
									value: {
										show: true,
										formatter: function (val) {
											return val + "%"
										}
									},
									total: {
										show: true,
										formatter: function (w) {
											return w.globals.seriesTotals[0] + "%"
										}
									}
								}
							}
						}
					}
				};

				var chart = new ApexCharts(document.querySelector("#overview-chart"), options);
				chart.render();
			}
		}

		var VisitorsChart = function () {
			if ($('#visitors-chart').length > 0) {
				var options = {
					series: [{
						name: 'Visitors',
						data: [90, 60, 70, 45, 40, 48, 27, 30]
					}],
					chart: {
						height: 230,
						type: 'bar',
						toolbar: false,
					},
					colors: ["var(--primary)"],
					legend: {
						show: false,
					},
					plotOptions: {
						bar: {
							columnWidth: '19%',
							distributed: true,
						}
					},
					dataLabels: {
						enabled: false
					},
					legend: {
						show: false
					},
					yaxis: {
						labels: {
							style: {
								fontSize: '13px',
								fontFamily: 'inter',
								color: 'var(--text)',
							}
						}
					},
					xaxis: {
						categories: [
							'Jan',
							'Feb',
							'Mar',
							'April',
							'May',
							'June',
							'July',
							'Aug',
						],
						labels: {
							style: {
								fontSize: '13px',
								fontFamily: 'inter',
								color: 'var(--text)',
							}
						},
						axisBorder: {
							show: false,
						},
						axisTicks: {
							show: false,
						},
					},
					grid: {
						strokeDashArray: 5,
						borderColor: '$border-color',
					}
				};
				var chart = new ApexCharts(document.querySelector("#visitors-chart"), options);
				chart.render();

				$(".visitors-tabs .nav-link").on('click', function () {
					var seriesType = $(this).attr('data-series');
					var data = [];
					switch (seriesType) {
						case "week":
							data = [30, 52, 25, 75, 52, 100, 25, 40];
							break;
						case "month":
							data = [30, 35, 45, 35, 55, 45, 35, 70];
							break;
						case "year":
							data = [50, 40, 55, 25, 90, 40, 35, 55];
							break;
						case "all":
							data = [34, 60, 75, 40, 45, 60, 30, 55];
							break;
						default:
							data = [50, 40, 55, 25, 45, 40, 35];
					}
					chart.updateSeries([
						{
							name: 'Revenue',
							data: data
						}
					]);
				})
			}
		}

		var UpdatesChart = function () {
			if ($('#updates-chart').length > 0) {
				var options = {
					series: [{
						name: 'Revenue',
						data: [0, 52, 25, 75, 52, 100, 25]
					}],
					chart: {
						height: 220,
						type: 'area',
						toolbar: false,
					},
					colors: ['var(--primary)'],
					dataLabels: {
						enabled: false
					},
					stroke: {
						show: true,
						width: 2,
						curve: 'straight',
						colors: ['var(--primary)'],
					},
					legend: {
						show: false
					},
					yaxis: {
						labels: {
							style: {
								fontSize: '13px',
								fontFamily: 'inter',
								color: 'var(--text)',
							}
						}
					},
					xaxis: {
						categories: [
							'Jan',
							'Feb',
							'Mar',
							'April',
							'May',
							'June',
							'July',
							'Aug',
						],
						labels: {
							style: {
								fontSize: '13px',
								fontFamily: 'inter',
								color: 'var(--text)',
							}
						},
						axisBorder: {
							show: false,
						},
						axisTicks: {
							show: false,
						},
					},
					fill: {
						opacity: 0.5,
						colors: 'var(--primary)',
						type: 'gradient',
						gradient: {
							colorStops: [

								{
									offset: 0.6,
									color: 'var(--primary)',
									opacity: .2
								},
								{
									offset: 0.6,
									color: 'var(--primary)',
									opacity: .15
								},
								{
									offset: 100,
									color: 'white',
									opacity: 0
								}
							],

						}
					},
					grid: {
						strokeDashArray: 5,
						borderColor: '$border-color',
					}

				};

				var chart = new ApexCharts(document.querySelector("#updates-chart"), options);
				chart.render();

				$(".updates-tabs .nav-link").on('click', function () {
					var seriesType = $(this).attr('data-series');
					var data = [];
					switch (seriesType) {
						case "week":
							data = [30, 52, 25, 75, 52, 100, 25, 45];
							break;
						case "month":
							data = [30, 35, 45, 35, 55, 45, 35, 45];
							break;
						case "year":
							data = [30, 40, 80, 25, 65, 40, 100, 45];
							break;
						case "all":
							data = [30, 60, 20, 60, 45, 100, 70, 45];
							break;
						default:
							data = [30, 40, 75, 55, 45, 100, 35];
					}
					chart.updateSeries([
						{
							name: 'Revenue',
							data: data
						}
					]);
				})
			}
		}
		var handleWorldMap = function (trigger = 'load') {
			var vmapSelector = $('#world-map');
			if (trigger == 'resize') {
				vmapSelector.empty();
				vmapSelector.removeAttr('style');
			}

			vmapSelector.delay(500).unbind().vectorMap({
				map: 'world_en',
				backgroundColor: 'transparent',
				borderColor: 'rgb(239, 242, 244)',
				borderOpacity: 0.25,
				borderWidth: 1,
				color: 'rgb(229 232 223)',
				enableZoom: true,
				hoverColor: 'rgb(29, 105, 214)',
				hoverOpacity: null,
				normalizeFunction: 'linear',
				scaleColors: ['#b6d6ff', '#005ace'],
				selectedColor: 'rgb(29, 105, 214)',
				selectedRegions: null,
				showTooltip: true,
				onRegionClick: function (element, code, region) {
					var message = 'You clicked "'
						+ region
						+ '" which has the code: '
						+ code.toUpperCase();

					alert(message);
				}
			});
		}

		/* Function ============ */
		return {
			init: function () {

			},


			load: function () {
				OverviewChart();
				VisitorsChart();
				UpdatesChart();
				handleWorldMap();


			},

			resize: function () {

			}
		}

	}();



	jQuery(window).on('load', function () {
		setTimeout(function () {
			dzChartlist.load();
		}, 1000);

	});
})(jQuery);
